# LAMMPS

[LAMMPS](http://lammps.sandia.gov/) (Large-scale Atomic/Molecular Massively Parallel Simulator) is a classical molecular dynamics code with a focus on materials modeling.

Keywords: `materials science`, `physics`, `chemistry`, `molecular dynamics`

## Available modules

There are several LAMMPS modules on Midway2 and Midway3 that you can check via `module avail lammps`:

=== "Midway2"
    ```
    ---------------------------- /software/modulefiles2 ----------------------------
    lammps/17Nov2016+intelmpi-5.1+intel-16.0
    lammps/23Jun2022+oneapi-2021  

    ```
===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    lammps/17Apr2024           lammps/22Jul2025      lammps/24Mar2022-gpu  
    lammps/20Sep2021           lammps/23Jun2022      lammps/29Aug2024      
    lammps/20Sep2021-gpu       lammps/23Jun2022-gpu  lammps/29Oct2020      
    lammps/21Nov2023(default)  lammps/24Mar2022
    ```
The `gpu` suffix indicates that this module supports GPU acceleration and should run on a GPU node.
You can then show the dependency of individual modules, for example, on Midway3 if you do
```
module show lammps/21Nov2023
```
you will get
```
-------------------------------------------------------------------
/software/modulefiles/lammps/21Nov2023:

module-whatis   {setup lammps 21Nov2023 compiled with the system compiler}
conflict        lammps
module          load intelmpi/2021.5+intel-2022.0 mkl/2022.0 cuda/11.5
prepend-path    PATH /software/lammps-21Nov2023-el8-x86_64/bin

```
???+ note
    LAMMPS is under active development. You are encouraged to build the latest stable version from [source code](https://github.com/lammps/lammps) in your own space using the provided [compilers](../compilers.md).

In this case you can see this module was compiled with `intelmpi/2021.5+intel-2022.0` and `mkl/2022.0`. After loading the module, you can run
```
lmp -h
```
to see the features that are supported by the executable `lmp`.

There are several LAMMPS binaries in the folder `/software/lammps-21Nov2023-el8-x86_64/bin`. The README file therein explains the difference between the binaries and how to build LAMMPS from source.

## Example job scripts

An example batch script to run LAMMPS is given below
```
#!/bin/bash
#SBATCH --job-name=lmp-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=caslake
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=16

module load lammps/21Nov2023

ulimit -l unlimited

cd $SLURM_SUBMIT_DIR

ntasks_per_node=$SLURM_NTASKS_PER_NODE
numnodes=$SLURM_JOB_NUM_NODES
n=$(( ntasks_per_node * numnodes ))

mpirun -np $n lmp_cpu -in in.txt
```

The following script illustrates how to run the LAMMPS binary built with the GPU package `lmp_gpu`.

```
#!/bin/bash
#SBATCH --job-name=lmp-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --gres=gpu:2
#SBATCH --constraint=v100

module load lammps/21Nov2023

ulimit -l unlimited

cd $SLURM_SUBMIT_DIR

ntasks_per_node=$SLURM_NTASKS_PER_NODE
numnodes=$SLURM_JOB_NUM_NODES
n=$(( ntasks_per_node * numnodes ))

mpirun -np $n lmp_gpu -in in.txt -sf gpu -pk gpu 2
```

The following script illustrates how to run the LAMMPS binary built with the KOKKOS package `lmp_kokkos_cuda` using 2 MPI processes on 2 CPU cores using 2 GPUs.

```
#!/bin/bash
#SBATCH --job-name=lmp-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=2
#SBATCH --gres=gpu:2
#SBATCH --constraint=v100

module load lammps/21Nov2023

ulimit -l unlimited

cd $SLURM_SUBMIT_DIR

ntasks_per_node=$SLURM_NTASKS_PER_NODE
numnodes=$SLURM_JOB_NUM_NODES
n=$(( ntasks_per_node * numnodes ))

mpirun -np $n lmp_kokkos_cuda -in in.txt -k on g 2 -sf kk -pk kokkos neigh half newton on
```
## Build LAMMPS from source

Since LAMMPS is under active development, it might be beneficial for you to build LAMMPS from source to get the new features, improvements, and bugfixes. 

Below is an example to illustrate how you build LAMMPS from source using the Intel oneAPI toolchain with GPU support for A100 GPUs on Midway3/Beagle3.

```
module load oneapi/2023.1 mkl/2023.1 cmake/3.26
git clone https://github.com/lammps/lammps.git
cd lammps
git checkout tags/stable_29Aug2024 -b stable_29Aug2024
mkdir build
cd build
cmake -C ../cmake/presets/basic.cmake \
      -D PKG_CLASS2=on -D PKG_AMOEBA=on -D PKG_ASPHERE=on -D PKG_REPLICA=on -DPKG_FEP=on \
      -D PKG_GPU=on -D GPU_API=cuda -D GPU_ARCH=sm_80 -D BUILD_MPI=yes -D BUILD_OMP=on \
      -D PKG_KOKKOS=on -D Kokkos_ARCH_PASCAL60=off -D Kokkos_ARCH_NATIVE=yes \
      -D Kokkos_ARCH_AMPERE80=ON -D Kokkos_ENABLE_CUDA=yes -D Kokkos_ENABLE_OPENMP=yes \
      -D CMAKE_CXX_COMPILER=`which mpicxx` -D MPI_C_COMPILER=`which mpicc` \
      -DFFT=MKL -DFFTW3_INCLUDE_DIR=$MKLROOT/include/fftw -DFFT_KOKKOS=CUFFT \
      ../cmake
make -j4
```

Note the GPU architecture (more specifically, compute capability) is defined for the KOKKOS package `Kokkos_ARCH_AMPERE80=ON`. The GPU package is by default compiled to support a wide range of GPU architectures including `sm_80`.

