import gymnasium as gym
import numpy as np
import warnings
import matplotlib.pyplot as plt
import wandb
import copy
from datetime import datetime
from typing import List

from controller.cmaes_cpg_vectorized import CPG
from cmaes import CMA
from controller.parameters import MantaRayControllerSpecificationParameterizer
from controller.specification.controller_specification import MantaRayCpgControllerSpecification
from controller.specification.default import default_controller_dragrace_specification
from morphology.morphology import MJCMantaRayMorphology

from morphology.specification.default import default_morphology_specification
from parameters import MantaRayMorphologySpecificationParameterizer
from task.drag_race import Move
from fprs.specification import RobotSpecification

from mujoco_utils.environment import MJCEnvironmentConfig
from dm_control import viewer
from dm_env import TimeStep
from gymnasium.core import ObsType

warnings.filterwarnings('ignore', category=DeprecationWarning)


class OptimizerSimulation:
    """
    This class is responsible for simulating the evolution of a population by means of an evolutionary strategy i.e. by distribution sampling
    of MantaRay agents. It is responsible for:
    - running the simulation
    - saving the results
    - visualizing the results
    - saving the results
    """
    def __init__(self,
                task_config: MJCEnvironmentConfig,
                robot_specification: RobotSpecification,
                parameterizer: MantaRayControllerSpecificationParameterizer,
                population_size: int,
                num_generations: int,
                outer_optimalization ,
                controller: CPG,
                skip_inner_optimalization: bool = False,
                record_actions: bool = False,
                action_spec=None,
                num_envs: int = 2,
                logging: bool = True,
                ) -> None:
        """
        :param outer_optimalization: the outer optimization algorithm responsible for 
        :param skip_inner_optimalization: whether to skip the inner optimization i.e. all actions are pre-computed to speed up the simulation
                                        this is a significant speed-up
        """
        self._task_config = task_config
        self._robot_specification = robot_specification
        self._parameterizer = parameterizer
        self._population_size = population_size
        self._num_generations = num_generations
        self._outer_optimalization = outer_optimalization
        self._controller = controller
        self._skip_inner_optimalization = skip_inner_optimalization
        self._record_actions = record_actions
        self._num_envs = num_envs
        self._logging = logging

        self._controller_specs = [default_controller_dragrace_specification() for _ in range(self._num_envs)]
        for controller_spec in self._controller_specs:
            self._parameterizer.parameterize_specification(specification=controller_spec)
        self._morph_specs = [default_morphology_specification() for _ in range(self._num_envs)]
        self._controllers: List[CPG] = [controller(specification=controller_spec) for controller_spec in self._controller_specs]

        self._gym_env = gym.vector.AsyncVectorEnv([lambda: Move().environment(morphology=MJCMantaRayMorphology(specification=self._morph_specs[env_id]),
                                                                  wrap2gym=True) for env_id in range(self._num_envs)])

        # self._gym_env = self._envs[0]#task_config.environment(morphology=morphology, 
        #                               #wrap2gym=True)
        self._action_spec = action_spec
        self._morphology_specification = self._robot_specification.morphology_specification
        self._controller_specification = self._robot_specification.controller_specification
        self._action_space = self._gym_env.action_space
        self._outer_rewards = np.zeros(shape=(self._num_generations, self._population_size))
        if self._skip_inner_optimalization:
            self._inner_rewards = None
        else:
            self._inner_rewards = np.zeros(shape=(self._num_generations,
                                                self._population_size, 
                                                task_config.simulation_time/task_config.control_timestep))
        if self._record_actions:
            self._actions = np.zeros(shape=(self._num_generations, 
                                            self._population_size, 
                                            8,  # action space
                                            int(task_config.simulation_time/task_config.control_timestep)))
            self._control_actions = np.zeros(shape=(self._num_generations, 
                                                    self._population_size, 
                                                    len(self._parameterizer.get_parameter_labels()),))
        # logging
        if self._logging:
            wandb.init(project="manta-ray", 
                    name=f"""{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}_test_logging""",
                        config={
                            "generations": self._num_generations,
                            "duration": self._task_config.simulation_time,
                            "control_timestep": self._task_config.control_timestep,
                            "population_size": self._population_size,
                            "sigma_outer_loop": self._outer_optimalization._sigma,
                        }
                    )
    
    def run_episode_single(self,
                           generation: int,
                           episode: int,
                           counter: int,
                           obs: ObsType,
                           env_id: int,
                           ):
        minimum, maximum = self._action_spec.minimum.reshape(-1, 1), self._action_spec.maximum.reshape(-1, 1)   # shapes (n_neurons, 1)
        if self._skip_inner_optimalization:
            normalised_action = (self._controllers[env_id].ask(observation=obs,
                                                               duration=self._task_config.simulation_time,
                                                               sampling_period=self._task_config.physics_timestep
                                                               )+1)/2
        else:
            normalised_action = (self._controllers[env_id].ask(observation=obs)+1)/2
        # assert np.all(normalised_action >= 0) and np.all(normalised_action <= 1), "Action is not in [0, 1]"

        # record actions
        scaled_action = minimum + normalised_action * (maximum - minimum)
        if self._record_actions and self._skip_inner_optimalization: 
            self._actions[generation, episode, :, :] = scaled_action
        elif self._record_actions and not self._skip_inner_optimalization:
            self._actions[generation, episode, :, counter] = scaled_action

    def run_episode_parallel(self,
                    generation: int,
                    episode: int,
                    ) -> float:
        done = False
        obs, _ = self._gym_env.reset()
        counter = 0
        while not done:
            scaled_action = np.zeros(shape=(self._num_envs, 8))
            for env_id in range(self._num_envs):
                # scaled_action[env_id, :] = 
                if not self._skip_inner_optimalization:
                    self.run_episode_single(generation=generation,
                                                            episode=episode+env_id,
                                                            counter=counter,
                                                            obs=obs,
                                                            env_id=env_id,
                                                            )
                elif obs["task/time"][0][0] == 0:
                    self.run_episode_single(generation=generation,
                                                            episode=episode+env_id,
                                                            counter=counter,
                                                            obs=obs,
                                                            env_id=env_id,
                                                            )
            obs, reward, terminated, truncated, info = self._gym_env.step(self._actions[generation, episode, :, counter])  # an action is a row
            done = np.all(np.logical_or(terminated, truncated))
            counter += 1
        return reward


    def run_generation(self,
                       generation: int,
                       ) -> None:
        solutions = []
        for agent in range(0, self._population_size, self._num_envs):
            outer_action = [self._outer_optimalization.ask() for _ in range(self._num_envs)]
            for env_id in range(self._num_envs):
                self._parameterizer.parameter_space(specification=self._controller_specs[env_id],
                                                    controller_action=outer_action[env_id])
            reward = self.run_episode_parallel(generation=generation, episode=agent)
            solutions += [(single_action, single_reward) for single_action, single_reward in zip(outer_action, reward)]
            for env_id in range(self._num_envs):
                self._outer_rewards[generation, agent+env_id] = reward[env_id]
                self._control_actions[generation, agent+env_id, :] = outer_action[env_id]
        self._outer_optimalization.tell(solutions)
    

    def run(self):
        for gen in range(self._num_generations):
            self.run_generation(generation=gen)
            if self._logging:    wandb.log({"generation": gen,
                                       "average": np.mean(self._outer_rewards[gen]),
                                        "worst": np.max(self._outer_rewards[gen]),
                                        "best": np.min(self._outer_rewards[gen]),
                                        })
    
    def get_best_individual(self) -> tuple[int, int]:
        """
        returns (generation, episode) of the best individual in the population"""
        indices = np.unravel_index(np.argmin(self._outer_rewards, axis=None), self._outer_rewards.shape)
        print("Best individual: ", indices, " , reward: ", self._outer_rewards[indices], " , action: ", self._control_actions[indices])
        for index, value in enumerate(self._control_actions[indices]):
            print(self._parameterizer.get_parameter_labels()[index], ": ", value)
        return indices
    
    def visualize(self):
        plt.plot(np.mean(self._outer_rewards, axis=1), label="average")
        plt.plot(self._outer_rewards.max(axis=1), label="max")
        plt.plot(self._outer_rewards.min(axis=1), label="min")
        plt.xlabel("generation")
        plt.ylabel("reward")
        plt.legend()
        plt.show()
    
    def visualize_inner(self, generation: int, episode: int):
        if self._record_actions is False:
            print("Record actions was skipped")
            return
        plt.plot(np.linspace(0, self._task_config.simulation_time, len(self._actions[generation, episode, index_left_pectoral_fin_x, :])), 
                 self._actions[generation, episode, index_left_pectoral_fin_x, :], 
                 label="left fin")
        plt.plot(np.linspace(0, self._task_config.simulation_time, len(self._actions[generation, episode, index_left_pectoral_fin_x, :])),
                 self._actions[generation, episode, index_right_pectoral_fin_x, :], 
                 label="right fin")
        plt.xlabel("time [seconds]")
        plt.ylabel("output")
        plt.legend()
        plt.show()

    def viewer(self,
               generation: int,
               episode: int,
               ) -> None:
        assert self._record_actions, "Cannot visualize actions if they are not recorded"
        dm_env = self._task_config.environment(morphology=MJCMantaRayMorphology(specification=self._morphology_specification), wrap2gym=False)
        def policy(timestep: TimeStep) -> np.ndarray:
            time = timestep.observation["task/time"][0]
            action = np.zeros(shape=self._action_space.shape[0])
            action: np.ndarray = self._actions[generation, episode, :, int(time/self._task_config.control_timestep)]
            return action
        viewer.launch(
            environment_loader=dm_env, 
            policy=policy
            )
    

if __name__ == "__main__":
    # morphology
    morphology_specification = default_morphology_specification()
    morphology = MJCMantaRayMorphology(specification=morphology_specification)
    # parameterizer = MantaRayMorphologySpecificationParameterizer(
    #     torso_length_range=(0.05, 2.),
    #     torso_radius_range=(0.05, 2.),
    #     )
    # parameterizer.parameterize_specification(specification=morphology_specification)
    

    # controller
    simple_env = Move().environment(morphology=MJCMantaRayMorphology(specification=morphology_specification), # TODO: remove this, ask Dries
                                                wrap2gym=False)
    observation_spec = simple_env.observation_spec()
    action_spec = simple_env.action_spec()
    names = action_spec.name.split('\t')
    index_left_pectoral_fin_x = names.index('morphology/left_pectoral_fin_actuator_x')
    index_right_pectoral_fin_x = names.index('morphology/right_pectoral_fin_actuator_x')
    controller_specification = default_controller_dragrace_specification()
    controller_parameterizer = MantaRayControllerSpecificationParameterizer(
        amplitude_fin_out_plane_range=(0, 1),
        frequency_fin_out_plane_range=(0, 1),
        offset_fin_out_plane_range=(0, np.pi),
    )
    controller_parameterizer.parameterize_specification(specification=controller_specification)
    cpg = CPG(specification=controller_specification,
              low=-1,
              high=1,
              )

    robot_spec = RobotSpecification(morphology_specification=morphology_specification,
                                    controller_specification=controller_specification)

    # morphology_space = parameterizer.get_target_parameters(specification=morphology_specification)
    cma = CMA(mean=np.random.uniform(low=0,
                                     high=1,
                                     size=len(controller_parameterizer.get_parameter_labels())),
              sigma=0.05,
              population_size=10,    # has to be more than 1
              lr_adapt=True,
              )
    sim = OptimizerSimulation(
        task_config=Move(simulation_time=20),
        robot_specification=robot_spec,
        parameterizer=controller_parameterizer,
        population_size=10,  # make sure this is a multiple of num_envs
        num_generations=10,
        outer_optimalization=cma,
        controller=CPG,
        skip_inner_optimalization=True,
        record_actions=True,
        action_spec=action_spec,
        num_envs=5,
        logging=True,
        )
    
    sim.run()
    sim.visualize()
    best_gen, best_episode = sim.get_best_individual()
    sim.viewer(generation=best_gen, episode=best_episode)
    sim.visualize_inner(generation=best_gen, episode=best_episode)

    # best_solution, best_fitness = cma.search()

    # show_video(frame_generator=run_episode())
    wandb.finish()