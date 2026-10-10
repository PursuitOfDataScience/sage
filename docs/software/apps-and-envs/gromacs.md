# GROMACS

[GROMACS](https://www.gromacs.org/) is a free and open-source software suite for high-performance molecular dynamics and output analysis.

Keywords: `biology`, `physics`, `chemistry`, `molecular dynamics`


## Available modules
There are several GROMACS modules on Midway2 and Midway3 that you can check via `module avail gromacs`:

=== "Midway2"
    ```
    ---------------------------- /software/modulefiles2 ----------------------------
    gromacs/5.0.7-cuda+intelmpi-5.1+intel-16.0      
    gromacs/5.1.4-cuda-7.5+intelmpi-5.1+intel-16.0  
    gromacs/2019.2+intelmpi-2018.2.199+intel-18.0   
    gromacs/2019.3+intelmpi-2018.2.199+intel-18.0   
    gromacs/2021.1+intelmpi-2019.up7+intel-19.1.1   

    ```
===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    gromacs/2020.4(default)  gromacs/2021.5  gromacs/2022.4  gromacs/2022.4-colvars 

    ```
You can then show the dependency of individual modules, for example,
```
module show gromacs/2021.5
```
which gives on Midway3
```
-------------------------------------------------------------------
/software/modulefiles/gromacs/2021.5:

module-whatis   {setup gromacs 2021.5 compiled with the system compiler}
conflict        gromacs
module          load gcc/7.4.0 openmpi/4.1.2+gcc-7.4.0 cuda/11.2 plumed/2.7.3
prepend-path    PATH /software/gromacs-2021.5-el8-x86_64/bin
prepend-path    LD_LIBRARY_PATH /software/gromacs-2021.5-el8-x86_64/lib64
prepend-path    LIBRARY_PATH /software/gromacs-2021.5-el8-x86_64/lib64
prepend-path    PKG_CONFIG_PATH /software/gromacs-2021.5-el8-x86_64/lib64/pkgconfig
prepend-path    CPATH /software/gromacs-2021.5-el8-x86_64/include
prepend-path    MANPATH /software/gromacs-2021.5-el8-x86_64/share/man
```

In this case you can see this module was compiled with `openmpi/4.1.2+gcc-7.4.0`, `cuda/11.2` and `plumed/2.7.3`. As a result, this version supports GPU acceleration and should be used on GPU nodes.

???+ note
    GROMACS is under active development. You are encouraged to build the latest stable version from [source code](https://github.com/gromacs/gromacs) in your own space using the provided [compilers](../compilers.md).

The GROMACS documentation contain useful information for improving performance of your specific calculations:

https://manual.gromacs.org/documentation/current/user-guide/mdrun-performance.html

## Example job script

An example batch script to run GROMACS for Midway3 is given as below
```
#!/bin/bash
#SBATCH --job-name=gmx-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint=v100
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=32

module load gromacs/2021.5

cd $SLURM_SUBMIT_DIR

export GMX_PATH=/software/gromacs-2021.5-el8-x86_64/bin
source $GMX_PATH/GMXRC

ntasks_per_node=$SLURM_NTASKS_PER_NODE
numnodes=$SLURM_JOB_NUM_NODES
n=$(( ntasks_per_node * numnodes ))

t=1000

mpirun -np $n gmx_mpi mdrun -ntomp 1 -pin on -nb gpu -nsteps $t \
   -v -s init.tpr
```
where `init.tpr` is an existing portable binary run input file.

<!---
There are two different primary configurations:

* **gromacs-X.Y.Z** is single precision (float)

* **gromacs-plumed-X.Y.Z+<compiler module>** is double precision, compiled with the stated compiler and MPI code, with PLUMED and Reconnaissance Metadynamics

`gromacs.sbatch` demonstrates how to run a short Gromacs job (the d.dppc test
case) in parallel.  Submit to the queue by:

```bash
cd $HOME/rcchelp/software/gromacs.rcc-docs
sbatch gromacs.sbatch
# and / or
sbatch gromacs-plumed.sbatch
```

The submission scripts can be modified to suit your needs
--->

