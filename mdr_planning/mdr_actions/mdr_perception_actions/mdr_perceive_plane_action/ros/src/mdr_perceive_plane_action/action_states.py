#!/usr/bin/python
import rospy
from pyftsm.ftsm import FTSMTransitions
from mas_execution.action_sm_base import ActionSMBase
from mas_perception_msgs.msg import PlaneList
from mas_perception_libs import ObjectDetector, RecognizeImageServiceProxy
from mdr_perceive_plane_action.msg import PerceivePlaneResult

class PerceivePlaneSM(ActionSMBase):
    def __init__(self, detection_service_proxy,
                 recog_service_name,
                 recog_model_name,
                 preprocess_input_module,
                 classify_object=True,
                 target_frame=None,
                 timeout_duration=1,
                 max_recovery_attempts=1):
        super(PerceivePlaneSM, self).__init__('PerceivePlane', [], max_recovery_attempts)
        self._detector = ObjectDetector(detection_service_proxy)
        self._recog_service_proxy = RecognizeImageServiceProxy(recog_service_name, recog_model_name,
                                                               preprocess_input_module)
        self._classify_object = classify_object
        self._timeout_duration = timeout_duration
        self._target_frame = target_frame
        self._detecting_done = False

    def running(self):
        detected_planes = None
        self._detecting_done = False
        self._detector.start_detect_objects(self.goal.plane_frame_prefix,
                                            self._detection_cb,
                                            self._target_frame)

        timeout = rospy.Duration.from_sec(self._timeout_duration)
        rate = rospy.Rate(10)   # 10Hz
        start_time = rospy.Time.now()
        while (rospy.Time.now() - start_time) < timeout:
            if self._detecting_done:
                if self._detector.plane_list is None:
                    rospy.logerr('[perceive_plane] No planes found')
                    self.result = self.set_result(False, detected_planes)
                    return FTSMTransitions.DONE
                detected_planes = self._detector.plane_list
            rate.sleep()

        if not self._detecting_done:
            rospy.logerr('[perceive_plane] A plane could not be found within the alloted time')
            self.result = self.set_result(False, detected_planes)
            return FTSMTransitions.DONE

        rospy.loginfo('[perceive_plane] Found %d plane(s)', len(detected_planes.planes))
        for plane in detected_planes.planes:
            image_messages = []
            classes = []
            probs = []
            for obj in plane.object_list.objects:
                if self._classify_object:
                    image_messages.append(obj.rgb_image)
                classes.append(obj.name)
                probs.append(obj.probability)

            if self._classify_object:
                rospy.loginfo('[perceive_plane] classifying objects')
                indices, classes, probs = self._recog_service_proxy.classify_image_messages(image_messages)
                for i in indices:
                    plane.object_list.objects[i].name = classes[i]
                    plane.object_list.objects[i].category = classes[i]
                    plane.object_list.objects[i].probability = probs[i]

            if len(classes) > 0:
                objects_str = ', '.join(['{0} ({1:.3f})'.format(cls, prob) for cls, prob in zip(classes, probs)])
                rospy.loginfo('[perceive_plane] on plane "{0}" (height {1:.3f}) found objects: {2}'
                              .format(plane.name, plane.plane_point.z, objects_str))
            else:
                rospy.logwarn('[perceive_plane] no objects recognized for plane "{0}" (height {1:.3f})'
                              .format(plane.name, plane.plane_point.z))

        self.result = self.set_result(True, detected_planes)
        return FTSMTransitions.DONE

    def _detection_cb(self):
        self._detecting_done = True

    def set_result(self, success, recognized_planes):
        result = PerceivePlaneResult()
        result.success = success
        if recognized_planes is None:
            result.recognized_planes = PlaneList()
            result.recognized_planes.planes = []
        else:
            result.recognized_planes = recognized_planes
        return result
