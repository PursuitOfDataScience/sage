# Libraries

There are several commonly used libraries that are available as modules on Midway2 and Midway3.
After loading a module into your environment, you can see which environment variables and paths it adds with:

```
module show [module-name]
```
These paths can be used in your Makefile or in the build configuration with CMake.

## GSL

The GNU Scientific Library [GSL](https://www.gnu.org/software/gsl/){:target='_blank'} is a numerical library for C and C++ programmers.

```
module load gsl
```
which sets up the paths and environment variables for the libraries.

## FFTW3

[FFTW3](https://www.fftw.org/){:target='_blank'} can be loaded via
```
module load fftw3
```
which sets up the paths and environment variables for the libraries.

## Intel oneAPI MKL

[Intel oneAPI MKL](https://www.intel.com/content/www/us/en/develop/documentation/get-started-with-mkl-for-dpcpp/top.html){:target='_blank'} can be loaded via
```
module load mkl
```
which sets up the paths and environment variables for the libraries. The MKL libraries provide core math functions, including BLAS, LAPACK, ScaLAPACK, sparse solvers, fast Fourier transforms, and vector math.

## NVIDIA HPC SDK

[NVIDIA HPC SDK](https://developer.nvidia.com/hpc-sdk){:target='_blank'} provides another toolset for compiling GPU-enabled C/C++/Fortran codes via OpenACC. NVIDIA HPC SDK also provides a set of GPU-optimized tools and math libraries. These compilers are available through the `nvhpc` module.

