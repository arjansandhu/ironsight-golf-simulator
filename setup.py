from setuptools import setup, find_packages

setup(
    name="ironsight-golf-simulator",
    version="0.1.0",
    description="macOS golf simulator connecting to OptiShot 2 swing pad",
    author="IronSight",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "PyQt6>=6.6.0",
        "PyQt6-WebEngine>=6.6.0",
        "opencv-python-headless>=4.9.0",
        "hidapi>=0.14.0",
        "numpy>=1.26.0",
        "scipy>=1.12.0",
    ],
    extras_require={
        "ai": ["anthropic>=0.40.0"],
        "package": ["py2app>=0.28.0"],
    },
    entry_points={
        "console_scripts": [
            "ironsight=src.main:main",
        ],
    },
)
