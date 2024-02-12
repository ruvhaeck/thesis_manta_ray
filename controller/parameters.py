import sys

import numpy as np
sys.path.insert(0,'/media/ruben/data/documents/unief/thesis/thesis_manta_ray/')
from typing import List

from fprs.parameters import ContinuousParameter
from fprs.specification_parameterizer import ControllerSpecificationParameterizer

from controller.specification.default import default_controller_dragrace_specification
from controller.specification.controller_specification import MantaRayCpgControllerSpecification


class MantaRayControllerSpecificationParameterizer(ControllerSpecificationParameterizer):
    tail_segment_0_z = 0
    tail_segment_0_y = 1
    tail_segment_1_z = 2
    tail_segment_1_y = 3
    right_fin_x = 4
    right_fin_z = 5
    left_fin_x = 6
    left_fin_z = 7
    def __init__(
            self,
            amplitude_fin_out_plane_range: tuple[float, float],
            frequency_fin_out_plane_range: tuple[float, float],
            offset_fin_out_plane_range: tuple[float, float],
            ) -> None:
        super().__init__()
        self._amplitude_fin_out_plane_l_range = amplitude_fin_out_plane_range
        self._frequency_fin_out_plane_l_range = frequency_fin_out_plane_range
        self._offset_fin_out_plane_l_range = offset_fin_out_plane_range
        self._amplitude_fin_out_plane_r_range = amplitude_fin_out_plane_range
        self._frequency_fin_out_plane_r_range = frequency_fin_out_plane_range
        self._offset_fin_out_plane_r_range = offset_fin_out_plane_range


    def parameterize_specification(
            self,
            specification: MantaRayCpgControllerSpecification
            ) -> None:
        omega = 4
        bias = np.pi
        specification.r.add_connections(connections=[(0, self.right_fin_x), 
                                                     (0, self.left_fin_x),
                                                     ],
                                        weights=[1, 1.],
                                        low=[0, 0], 
                                        high=[1, 1],
                                        )
        specification.omega.add_connections(connections=[(0, self.right_fin_x), 
                                                         (0, self.left_fin_x),
                                                         ],
                                                weights=np.ones(shape=(2, ))*np.pi*2*omega,
                                                low=np.zeros(shape=(2, )),
                                                high=np.ones(shape=(2, ))*2*np.pi*omega)
        connections = [(4, 6), (6, 4),] # connection right-left fin
        specification.weights.set_connections(connections=connections,
                                                weights=[5, 5],
                                                )
        specification.phase_biases.add_connections(connections=connections,
                                                weights=[-bias, bias], 
                                                low=-np.ones(shape=(2, ))*np.pi,
                                                high=np.ones(shape=(2, ))*np.pi)
        
        
    def parameter_space(self,
                        specification: MantaRayCpgControllerSpecification,
                        controller_action: np.ndarray,
                        ) -> None:
        """
            args:
                controller_action: np.ndarray of shape (num_neurons, ) within range [0, 1]

            scales the controller_action to the range of the parameter
        """
        assert np.all(controller_action >= 0) and np.all(controller_action <= 1), f"[MantaRayCpgControllerSpecification] controller_action '{controller_action}' is not within range [0, 1]"
        # get the right length due to symmetry
        amplitude = controller_action[0]
        offset = controller_action[1]
        frequency = controller_action[2]
        phase_bias = controller_action[3]
        
        # updating specification
        specification.r.value = specification.r.low + amplitude * (specification.r.high - specification.r.low)
        specification.x.value = specification.x.low + offset * (specification.x.high - specification.x.low)
        specification.omega.value = specification.omega.low + frequency * (specification.omega.high - specification.omega.low)
        specification.phase_biases.value = specification.phase_biases.low + phase_bias * (specification.phase_biases.high - specification.phase_biases.low)

        # fin_amplitude = controller_action[0]
        # fin_frequency = controller_action[1]*2*np.pi*3  # max 3 Hz
        # phase_bias = controller_action[2]*np.pi
        # weight = controller_action[3]*10
        # specification.r.value  = [0, 0, fin_amplitude, fin_amplitude]
        # specification.omega.value = [0, 0, fin_frequency, fin_frequency]
        # specification.phase_biases.value = [-phase_bias, phase_bias]
        # specification.weights.value = [weight, weight]
        # specification.scaled_update(update=controller_action)

    

    def get_parameter_labels(
            self,
            ) -> List[str]:
        return ["fin_amplitude", "fin_offset", "frequency", "phase_bias"]



if __name__ == '__main__':
    controller_specification = default_controller_dragrace_specification()

    parameterizer = MantaRayControllerSpecificationParameterizer(
        amplitude_fin_out_plane_range=(0, 1),
        frequency_fin_out_plane_range=(0, 3),
        offset_fin_out_plane_range=(-1, 1),
        left_fin_x=4,
        right_fin_x=6
    )
    parameterizer.parameterize_specification(specification=controller_specification)

    print("All parameters:")
    print(f"\t{controller_specification.parameters}")
    print()
    print("Parameters to optimise:")
    for parameter, label in zip(
            parameterizer.get_target_parameters(specification=controller_specification),
            parameterizer.get_parameter_labels(specification=controller_specification)
            ):
        print(f"\t{label}\t->\t{parameter}")