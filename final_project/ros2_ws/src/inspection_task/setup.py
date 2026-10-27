from setuptools import find_packages, setup

package_name = "inspection_task"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Workshop Team",
    maintainer_email="todo@example.com",
    description="Audited CRANE+ V2 joint trajectory publisher reused by the camera demo.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "pose_publisher = inspection_task.pose_publisher:main",
        ],
    },
)
