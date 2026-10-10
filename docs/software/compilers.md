# Compilers

In addition to having access to the provided software modules, you can always
compile and use your codes or other open-source codes on Midway. You can check out
the source files from GitHub (via ` git clone`) or copy from your local machine
to your own space on Midway (e.g. under `/home` or `/project`).

Depending on the requirements of the codes, you can load the compilers and libraries
that are provided as modules.

GNU GCC, Intel and AMD compilers are provided through modules on Midway2 and Midway3. The table below lists details about each of the module-provided compilers.

=== "Midway2"
      | Vendor |  Module | Language      | Compiler        |
      | -------| --------| -----------   |  -------------- |
      | GNU    | `gcc`   | C <br>C++<br>Fortran  | `gcc`<br>`g++`<br>`gfortran` |
      | Intel  | `intel`, `oneapi` | C <br>C++<br>Fortran  | `icc`, `icx`<br>`icpc`, `icpx`, `dpcpp`<br>`ifort`, `ifx` |
===+ "Midway3"
      | Vendor |  Module | Language      | Compiler        |
      | -------| --------| -----------   |  -------------- |
      | GNU    | `gcc`   | C <br>C++<br>Fortran  | `gcc`<br>`g++`<br>`gfortran` |
      | Intel  | `intel`, `oneapi` | C <br>C++<br>Fortran  | `icc`, `icx`<br>`icpc`, `icpx`, `dpcpp`<br>`ifort`, `ifx` |
      | AMD    | `aocc`  | C <br>C++         | `clang`<br>`clang++`   |
      | NVIDIA | `nvhpc` | C <br>C++<br>Fortran         | `nvc`<br>`nvc++`<br>`nvfortran` |

!!! note
    AMD compilers are available on the Midway3 AMD cluster and with `module use /software/modulefiles-amd`.

Each module may have different versions. The default version is always loaded if you do not specify explicitly with `module load`.
You should check with `module avail` to see what versions are available. For example, on Midway3 `module avail gcc` will return

```
---------------------------- /software/modulefiles -----------------------------
gcc/7.4.0  gcc/10.2.0(default) gcc/12.2.0 gcc/13.2.0
```
and `module avail oneapi`
```
---------------------------- /software/modulefiles -----------------------------
oneapi/2023.1 oneapi/2024.1 oneapi/2024.2
```
You can check the changes to the environment variables made by a particular module by the `module show` command.

## Multithreading with OpenMP

To compile your code or software packages that support multithreading with OpenMP, you just need to add to the compiling flags `-fopenmp` for GNU GCC and AMD compilers and `-qopenmp` for Intel compilers.

## Message-passing interface (MPI)

To compile your code or software packages with MPI, you need to load the MPI modules that are available.
The list of libraries and software suites that provide MPI libraries is given as below.

=== "Midway2"
      | Implementation | Module                  | Language             | Wrapper                             |
      |----------------|-------------------------|----------------------|-------------------------------------|
      | OpenMPI        | `openmpi`               | C <br>C++<br>Fortran | `mpicc`<br>`mpicxx`<br>`mpif90`     |
      | MPICH          | `mpich`                 | C <br>C++<br>Fortran | `mpicc`<br>`mpicxx`<br>`mpif90`     |
      | Intel          | `intelmpi`<br>`oneapi` | C <br>C++<br>Fortran | `mpiicc`<br>`mpiicpc`<br>`mpiifort` |
      | NVIDIA         | `nvhpc`                 | C <br>C++<br>Fortran | `nvc`<br>`nvc++`<br>`nvfortran`     |
===+ "Midway3"
      | Implementation | Module                  | Language             | Wrapper                             |
      |----------------|-------------------------|----------------------|-------------------------------------|
      | OpenMPI        | `openmpi`               | C <br>C++<br>Fortran | `mpicc`<br>`mpicxx`<br>`mpif90`     |
      | MPICH          | `mpich`                 | C <br>C++<br>Fortran | `mpicc`<br>`mpicxx`<br>`mpif90`     |
      | Intel          | `intelmpi`<br>`oneapi` | C <br>C++<br>Fortran | `mpiicc`<br>`mpiicpc`<br>`mpiifort` |
      | NVIDIA         | `nvhpc`                 | C <br>C++<br>Fortran | `nvc`<br>`nvc++`<br>`nvfortran`     |

!!! note
    For AMD C/C++ compilers `clang` and `clang++` (available with `module load aocc`), you need to load a MPI module (e.g. `openmpi` or `intelmpi`) to compile MPI codes.
!!! note
    Experienced users can build the MPI libraries of their preferences in their own space using the provided compilers above.

### MPI Example
If you need to compile your software packages from source, you can download the software source code from GitHub to your space, load the compiler modules and build the codes. In this tutorial, let us build [LAMMPS](https://github.com/lammps/lammps) from source code:

```
cd /project/[pi-folder]/[your-cnetid]
git clone https://github.com/lammps/lammps.git
cd lammps
mkdir build && cd build
```

Load the modules for the preferred compiler, MPI libraries and MKL. Then run cmake to configure the build and finally build the code:
```
module load mpich/3.4.3+gcc-10.2.0 mkl/2023.1 cmake/3.26
cmake ../cmake -C ../cmake/presets/basic.cmake -DFFT=MKL -DFFTW3_INCLUDE_DIR=$MKLROOT/include/fftw
make -j4
```

If the build succeeds, you will see a LAMMPS binary, namely `lmp`, generated under the folder `/project/[pi-folder]/lammps/[your-cnetid]/build`.

You can use other compilers (Intel oneAPI, GNU GCC) and MPI libraries (OpenMPI, MPICH). For GPU codes, you can use NVIDIA HPC SDK and Intel oneAPI. More information on the available development tools is given in the [GPU codes](#gpu-codes) section below. 

## GPU codes

To compile GPU codes, you can use NVIDIA CUDA Toolkit and HPC SDK (with OpenACC), Intel OneAPI (with SYCL), and GNU GCC 4.0+ (with GPU offloading). 

### NVIDIA toolsets

#### CUDA Toolkit

There are several [NVIDIA CUDA](https://developer.nvidia.com/cuda-toolkit){:target='_blank'} toolkit versions on Midway2 and Midway3. You can check the version provided with `module avail cuda`. On Midway3 there are several CUDA versions:

```
--------------------------- /software/modulefiles -----------------------------
cuda/10.2  cuda/11.2  cuda/11.3  cuda/11.5 cuda/11.7 cuda/12.0 cuda/12.2
```
The current version of the GPU driver on the GPU nodes supports all the above CUDA toolkit versions. You can check the GPU driver version via the `nvidia-smi` command after loading a `cuda` module.

!!! note
     Although you can compile your CUDA code on the login node with the CUDA toolkit module loaded,
     running the generated binary on the login node will fail because there is no GPU on the login node.

#### NVIDIA HPC SDK

[NVIDIA HPC SDK](https://developer.nvidia.com/hpc-sdk){:target='_blank'} provides another toolset for compiling GPU-enabled C/C++/Fortran codes via OpenACC. NVIDIA HPC SDK also provides a set of GPU-optimized tools and math libraries. These compilers are available through the `nvhpc` module.
```
module load nvhpc
```
and check for the location of the compilers
```
which nvc++
which nvfortran
```
### Intel oneAPI

The [DPC++ Compiler](https://intel.github.io/llvm-docs/GetStartedGuide.html){:target='_blank'} compiles C++ and SYCL* source files with code for both CPU and a wide range of compute accelerators such as GPU and FPGA. You can load the `oneapi` module on Midway2 to get access to this compiler:
```
module load oneapi
```
and remember to source the shell script to setup the necessary environment variables:
```
source /software/oneapi-2021.beta7-el7-x86_64/inteloneapi/setvars.sh
```
and check for the location of the compilers
```
which dpcpp
```
## Go

[Go](https://go.dev/){:target='_blank'} is an open-source compiled programming language that gain an rapidly increasing interest and usage by the industry.  Although Go is not a traditional compiler, we include it here for convenience.
You can load Go as a module on Midway3.

## Java

Java is available as modules on Midway2 and Midway3. You can check the available modules via `module avail java`.