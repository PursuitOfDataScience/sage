# Software

## R and Python Virtual Environments
Users can install R or Python packages through the internal web proxy. Once authentication is successful with UChicago credentials, users can install research software in their virtual environments.

```
module load proxy
proxy 2h
```
The proxy command will prompt for authentication. Users can also specify a time limit to avoid repeated authentication prompts.

## Spack Package Manager
Spack is an HPC package manager that can be used to build scientific software with complex dependency chains.

```
module load spack                           # activate Spack
module use /software/spack-modules          # add Spack modules to MODULEPATH
module avail                                # see available spack modules next to the system modules
module load gdal                            # load GDAL and all its dependencies
```

Installed packages are stored in `/software/spack-apps/` with 7-character hash suffixes. Only explicitly installed packages appear in `module avail`; implicit dependencies are hidden but loaded automatically. Users are encouraged to create Spack virtual environments to ensure project reproducibility and isolation. 