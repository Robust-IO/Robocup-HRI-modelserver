FROM ros:humble-ros-base
WORKDIR /opt/robocup
COPY src/ src/
RUN . /opt/ros/humble/setup.sh && colcon build --merge-install --cmake-args -DBUILD_TESTING=OFF
COPY start.sh /opt/robocup/start.sh
CMD ["bash", "/opt/robocup/start.sh"]
