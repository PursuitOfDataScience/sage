# NWChem

[NWChem](https://www.nwchem-sw.org/) is an open source software package for performing high-performance computational chemistry calculations. The software contains tools that are scalable both in their ability to efficiently treat large scientific problems, and in their use of available computing resources from high-performance parallel supercomputers to conventional workstation clusters.

Check out the NWChem documentation for more information: https://nwchemgit.github.io/index.html

Keywords: `quantum chemistry`, `chemistry`

## Available modules
You can check the available `nwchem` module(s) installed via `module avail nwchem`:

===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    nwchem/7.2.2
    ```

You can use `module show` to see the dependencies and environment variables set by a specified `nwchem` module, for example, `module show nwchem/7.2.2`:

```
-------------------------------------------------------------------
/software/modulefiles/nwchem/7.2.2:

module-whatis   {setup nwchem 7.2.2 compiled with the system compiler}
conflict        nwchem
module          load oneapi/2023.1 mkl/2023.1
prepend-path    PATH /software/nwchem-7.2.2-el8-x86_64/bin
prepend-path    LD_LIBRARY_PATH /software/nwchem-7.2.2-el8-x86_64/lib
prepend-path    LIBRARY_PATH /software/nwchem-7.2.2-el8-x86_64/lib
-------------------------------------------------------------------
```


## Example job script

An example batch script to run NWChem for Midway3 is given as below
```
#!/bin/bash
#SBATCH --job-name=nwchem-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=8
#SBATCH --mem=64GB

module load nwchem/7.2.2

ulimit -l unlimited

cd $SLURM_SUBMIT_DIR

nodes=$SLURM_NNODES
ppn=$SLURM_NTASKS_PER_NODE
n=$(( ppn * nodes ))

mpirun -n $n nwchem input.nw
```

An example input file `input.nw` can be as follows:
```
start h2o 
title "Water in 6-31g basis set" 

geometry units au  
  O      0.00000000    0.00000000    0.00000000  
  H      0.00000000    1.43042809   -1.10715266  
  H      0.00000000   -1.43042809   -1.10715266 
end  
basis  
  H library 6-31g  
  O library 6-31g  
end
task scf
```

## Build NWChem from source

Since NWChem is under active development, it might be beneficial for you to build NWChem from source to get the new features, improvements, and bugfixes. 

Below is an example to illustrate how you build NWChem from source using the Intel oneAPI toolchain on Midway3/Beagle3.

```
module load oneapi/2023.1 mkl/2023.1 python/anaconda-2021.5 cmake 3.26
cd /your/own/space
git clone https://github.com/nwchemgit/nwchem.git
cd nwchem
git checkout tags/v7.2.2-release -b v7.2.2
export NWCHEM_TOP=/your/own/space/nwchem
export NWCHEM_TARGET=LINUX64
export NWCHEM_MODULES="all python"
export USE_MPI=y
export USE_MPIF=y
export USE_MPIF4=y
export USE_SCALAPACK=y
export SCALAPACK="-L$MKLROOT/lib/intel64 -lmkl_scalapack_ilp64 -lmkl_intel_ilp64 -lmkl_core -lmkl_sequential -lmkl_blacs_intelmpi_ilp64 -lpthread -lm"
export SCALAPACK_SIZE=8
export SCALAPACK_LIB="$SCALAPACK"
export BLAS_SIZE=8
export BLASOPT="-L$MKLROOT/lib/intel64 -lmkl_intel_ilp64 -lmkl_core -lmkl_sequential -lmkl_core -liomp5 -lpthread -ldmapp -lm"
export LAPACK_LIB="-L$MKLROOT/lib/intel64 -lmkl_intel_ilp64 -lmkl_core -lmkl_sequential -lmkl_core -liomp5 -lpthread -ldmapp -lm"
export PYTHONVERSION=3.8
export PYTHONLIBTYPE=so
export CC=mpiicc
export FC=mpiifort
make nwchem_config
make
```