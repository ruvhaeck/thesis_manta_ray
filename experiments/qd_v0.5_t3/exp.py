import sys
import os
import shutil

from thesis_manta_ray.controller.quality_diversity import Archive, MapElites
from thesis_manta_ray.morphology.specification.default import default_morphology_specification
from thesis_manta_ray.morphology.morphology import MJCMantaRayMorphology
from thesis_manta_ray.controller.specification.default import default_controller_dragrace_specification 
from thesis_manta_ray.controller.specification.controller_specification import MantaRayCpgControllerSpecification
from thesis_manta_ray.controller.parameters import MantaRayControllerSpecificationParameterizer
from thesis_manta_ray.controller.cmaes_cpg_vectorized import CPG

from thesis_manta_ray.task.drag_race import MoveConfig, Task
from fprs.specification import RobotSpecification
from cmaes import CMA

import numpy as np

# set to False if you want to reload the latest version of the simulation and start from scratch
continue_where_stopped = False



# copy the evolution_simulation.py file to this folder such that the visualizer can always be used after an experiment
src = "/media/ruben/data/documents/unief/thesis/thesis_manta_ray/evolution_simulation.py"
dest = "/media/ruben/data/documents/unief/thesis/thesis_manta_ray/experiments/qd_v0.5_t3/evolution_simulation_correct_version.py"

if not continue_where_stopped:
    shutil.copy2(src, dest)
    from evolution_simulation import OptimizerSimulation
else:
    from evolution_simulation_correct_version import OptimizerSimulation


if __name__ == "__main__":
    # morphology
    morphology_specification = default_morphology_specification()
    morphology = MJCMantaRayMorphology(specification=morphology_specification)    

    # controller
    simple_env = MoveConfig().environment(morphology=MJCMantaRayMorphology(specification=morphology_specification), # TODO: remove this, ask Dries
                                                wrap2gym=False)
    observation_spec = simple_env.observation_spec()
    action_spec = simple_env.action_spec()
    names = action_spec.name.split('\t')
    index_left_pectoral_fin_x = names.index('morphology/left_pectoral_fin_actuator_x')
    index_right_pectoral_fin_x = names.index('morphology/right_pectoral_fin_actuator_x')
    controller_specification = default_controller_dragrace_specification(action_spec=action_spec)
    controller_parameterizer = MantaRayControllerSpecificationParameterizer(
        amplitude_fin_out_plane_range=(0, 1),
        frequency_fin_out_plane_range=(0, 1),
        offset_fin_out_plane_range=(0, np.pi),
    )
    controller_parameterizer.parameterize_specification(specification=controller_specification)
    print(f"controller: {controller_specification}")
    cpg = CPG(specification=controller_specification,
              low=-1,
              high=1,
              )

    robot_spec = RobotSpecification(morphology_specification=morphology_specification,
                                    controller_specification=controller_specification)

    # morphology_space = parameterizer.get_target_parameters(specification=morphology_specification)
    bounds = np.zeros(shape=(len(controller_parameterizer.get_parameter_labels()), 2))
    bounds[:, 1] = 1
    # parameters: ['fin_amplitude_left', 'fin_offset_left', 'frequency_left', 'phase_bias_left', 'fin_amplitude_right', 'fin_offset_right', 'frequency_right', 'phase_bias_right']
    archive = Archive(parameter_bounds=[(0, 1) for _ in range(len(controller_parameterizer.get_parameter_labels()))],
                      feature_bounds=[(-np.pi, np.pi), (-np.pi/2, np.pi/2), (-np.pi, np.pi)], 
                      resolutions=[10, 10, 10],
                      parameter_names=controller_parameterizer.get_parameter_labels(), 
                      feature_names=["roll", "pitch", "yawn"],
                      symmetry = [('phase_bias_right', 'phase_bias_left'), 
                                ('frequency_right', 'frequency_left'), 
                                ('fin_offset_right', 'fin_offset_left'), 
                                ('fin_amplitude_right', 'fin_amplitude_left'),
                                ],
                        max_items_per_bin=1
                      )
    map_elites = MapElites(archive, archive_file="experiments/qd_v0.5_t3/sim_objects/archive.pkl")

    sim = OptimizerSimulation(
        task_config=MoveConfig(simulation_time=3, 
                         velocity=0.5,
                         reward_fn="(E + 200*Δx) * (Δx)",
                         task_mode="random_target",),
        robot_specification=robot_spec,
        parameterizer=controller_parameterizer,
        population_size=10,  # make sure this is a multiple of num_envs
        num_generations=2000,
        outer_optimalization=map_elites,#cma,
        controller=CPG,
        skip_inner_optimalization=True,
        record_actions=True,
        action_spec=action_spec,
        num_envs=10,
        logging=False,
        )
    
    sim.run()
    # best_gen, best_episode = sim.get_best_individual()
    # # sim.visualize()
    # sim.viewer_gen_episode(generation=best_gen, episode=best_episode)
    map_elites.optimization_info(store="experiments/qd_v0.5_t3/plots/opt_info.html")
    archive.plot_grid_3d(x_label="roll", y_label="pitch", z_label="yawn", store="experiments/qd_v0.5_t3/plots/grid.html")
    sim.finish(store=True, name="qd_v0.5_t3/sim_objects/sim")