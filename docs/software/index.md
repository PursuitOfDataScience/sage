# Software

## Private Software 

All users can install software packages privately in their home and project directories in accordance with the [RCC Terms of Use](https://rcc.uchicago.edu/about-rcc/rcc-user-policy). Users can compile and install software while connected to the login nodes unless the process is time- or memory-consuming. In such cases, it is recommended to use **compute nodes**; however, note that compute nodes do not have access to the internet. See [Interactive Jobs](../slurm/sinteractive.md) for how to start and use a `sinteractive` session. 

## Shared Software

RCC uses [Environment Modules](http://modules.sourceforge.net){:target='_blank'} for managing software packages and libraries that would otherwise conflict with one another. 

When you first log in to RCC clusters, you will be placed in a basic user environment with minimal software available. The `module` system is a script-based system used to manage the user environment and to activate software packages. You must first load the corresponding software module to access software packages installed on RCC clusters. 

Basic `module` commands:

| Command  | Description | 
| --------- | --------- | 
| `module avail`          |   lists all available software modules            |    
| `module avail [name]`   |   lists modules matching [name]                   |
| `module load [name]`    |   loads the named module                          |
| `module unload [name]`  |   unloads the named module                        |
| `module list`           |   lists the modules currently loaded for the user |

!!! note "Module dependencies"
    Note that some modules require other specific modules, i.e., dependencies, to be loaded (or unloaded). If there is a conflict, you must explicitly unload the conflicting module (`module unload ...`), then load the desired module again. In certain cases, usually with loading an out-of-date module, you may get an error such as `Error: Requirement...` if a dependency is absent. In those situations, you can try `module load -f <module>` to force the module to load.

!!! note "Note on software for AMD CPUs" 
    For the `amd` partitions on Midway3, you need the software modules built specifically for AMD CPUs:

    ```
    module use /software/modulefiles-amd
    module avail
    ```

## Requesting a software package installation 
If you need software not currently available in the module system and believe that multiple research groups can benefit from installing this software, send a detailed request to our [Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'} providing:

1. The complete name of the software package 
2. The exact version number 
3. A link to the package website 
4. A paragraph explaining why this software is crucial for your research and why it should be available on RCC clusters 

## Commonly used software packages

This guide contains instructions for some commonly used applications and environments, including: 

* [AlphaFold](../software/apps-and-envs/alphafold.md)
* [Apptainer & Singularity](../software/apps-and-envs/singularity.md)
* [BinSanity](../software/apps-and-envs/binsanity.md)
* [CESM](../software/apps-and-envs/cesm.md)
* [Charliecloud](../software/apps-and-envs/charliecloud.md)
* [CryoSPARC](../software/apps-and-envs/cryosparc.md)
* [CUDA-Q](../software/apps-and-envs/cudaq.md)
* [Gaussian](../software/apps-and-envs/gaussian.md)
* [GROMACS](../software/apps-and-envs/gromacs.md) 
* [Jupyter](../software/apps-and-envs/jupyter.md)
* [LAMMPS](../software/apps-and-envs/lammps.md)
* [MeshLab](../software/apps-and-envs/meshlab.md)
* [MATLAB](../software/apps-and-envs/matlab.md)    
* [Mathematica](../software/apps-and-envs/mathematica.md)
* [MetaBAT2](../software/apps-and-envs/metabat2.md)
* [NAMD](../software/apps-and-envs/namd.md)
* [NWChem](../software/apps-and-envs/nwchem.md)
* [OpenMM](../software/apps-and-envs/openmm.md)
* [OpenPose](../software/apps-and-envs/openpose.md)
* [ORCA](../software/apps-and-envs/orca.md)
* [Perl](../software/apps-and-envs/perl.md) 
* [Python](../software/apps-and-envs/python.md)
* [R and RStudio](../software/apps-and-envs/r.md)
* [SLiM](../software/apps-and-envs/slim.md)
* [Snakemake](../software/apps-and-envs/snakemake.md)
* [Space Ranger](../software/apps-and-envs/spaceranger.md)
* [Spark](../software/apps-and-envs/spark.md)
* [Stata](../software/apps-and-envs/stata.md) 
* [TensorFlow and PyTorch](../software/apps-and-envs/tf-and-torch.md)

* [VS Code (SCode)](../software/apps-and-envs/scode/main.md)
* [WRF](../software/apps-and-envs/wrf.md)


Each software page follows the same layout: a short introduction with keywords, **Available modules**, **Example job scripts**, **Build from source** (where applicable), and **Getting help**.

## Getting help with AI assistants

An AI assistant such as [Claude](https://claude.ai){:target='_blank'} can help you interpret error messages, adapt the example job scripts in this guide, or find the right options in a software package's documentation. You get the best answers when you give it the full context:

- the software and module version (e.g., `module load lammps/21Nov2023`)
- the cluster and partition you are using (e.g., Midway3, `caslake`, 48 cores and 192 GB per node)
- your job script and, if relevant, your input file
- the last 20–30 lines of the job's `.out`/`.err` files

For example:

```text
I'm running <software> (module <module-name>/<version>) on a Slurm
cluster (partition caslake, 48 cores and 192 GB per node). My job script is:

<paste your job script>

The job fails with this error:

<paste the last 20-30 lines of the .err/.out file>

What is causing this, and how should I change the script?
```

!!! warning
    Do not paste passwords, tokens, unpublished results, or regulated/sensitive data (e.g., from SDE2/SDE3 projects) into an AI assistant. Always check suggested commands before running them, especially commands that delete or move files. If you are unsure, [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}.
