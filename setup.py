"""Setup script for RemarkableSync."""

from pathlib import Path

from setuptools import find_packages, setup

# Read requirements from requirements.txt
requirements_file = Path(__file__).parent / "requirements.txt"
with open(requirements_file, encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

# Read version from src/__version__.py
version_file = Path(__file__).parent / "src" / "__version__.py"
version = {}
with open(version_file, encoding="utf-8") as f:
    exec(f.read(), version)

# Read long description from README
readme_file = Path(__file__).parent / "README.md"
with open(readme_file, encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="remarkablesync",
    version=version["__version__"],
    description="Backup and convert reMarkable tablet notebooks to PDF",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Jeff Steinbok",
    author_email="",  # Add your email if desired
    url="https://github.com/JeffSteinbok/RemarkableSync",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*", "release"]),
    py_modules=["reMarkableSync"],
    include_package_data=True,
    install_requires=requirements,
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "reMarkableSync=reMarkableSync:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Utilities",
    ],
    keywords="remarkable tablet backup pdf converter",
)
