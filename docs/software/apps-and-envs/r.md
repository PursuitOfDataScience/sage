[R](https://cran.r-project.org) is a powerful tool for quantitative research and data analysis across various fields. This document describes how to use R on the Midway clusters.

## Table of Contents
- [Introduction](#introduction)
- [Available R Modules](#available-r-modules)
- [Using R for High-Performance Computing (HPC)](#using-r-for-high-performance-computing-hpc)
- [Installing R Packages](#installing-r-packages)
- [Using the renv Package for Reproducibility](#using-the-renv)
- [Best Practices](#best-practices)
- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)

---

## Introduction
R is a powerful tool for quantitative research and data analysis across a variety of fields. On the Midway clusters, R is available as centrally maintained modules, supporting both interactive and batch (HPC) workflows. This guide covers best practices for installing, configuring, and running R, including reproducibility and performance tips for both Midway2 and Midway3.

---

## Available R Modules

To see the list of available R modules:
```bash
module avail R
```

To check available RStudio IDE modules:
```bash
module avail rstudio
```

When using RStudio, it is recommended to connect to the RCC cluster via ThinLinc for a smoother experience.

---

=== "Midway3"

    **Available R Versions:**

    - `R/3.6.3`
    - `R/4.0.3`
    - `R/4.1.0`
    - `R/4.2.0`
    - `R/4.2.1`
    - `R/4.2.1-no-openblas` *(built with default BLAS; no OpenBLAS/MKL acceleration)*
    - `R/4.2.2`
    - `R/4.2.3`
    - `R/4.3.1`
    - `R/4.4.1` **(default)**
    - `R/4.4.1+oneapi-2024.2.0` *(Intel oneAPI build, see below)*
    - `R/4.4.2+gcc-13.2.0` *(built with GCC 13.2.0, see below)*

    ??? info "Build Details (click to expand)"
        - Most R modules are built with the system GCC compiler (`8.4.1`).
        - `R/4.2.1-no-openblas` is built with the default BLAS (no OpenBLAS or MKL), which may result in slower linear algebra performance.
        - `R/4.4.1+oneapi-2024.2.0` is built with Intel oneAPI 2024.2.0 and linked to Intel's Math Kernel Library (MKL). This provides maximum performance for matrix and linear algebra operations, leveraging the latest Intel hardware/software optimizations. The module automatically loads `oneapi/2024.2` and sets all relevant paths and environment variables for you. Use this if you need high-performance math.
        - `R/4.4.2+gcc-13.2.0` is built with GCC 13.2.0. Use this version if your R library requires a newer GCC toolchain (for example, the `arrow` package or other modern C++-dependent libraries).

    **Geospatial Meta-Module:**
    - There is a meta-module for geospatial applications: `gis/R-4.2.1`. Loading this module will automatically load `R/4.2.1` along with all required geospatial libraries (`GDAL`, `GEOS`, `PROJ`, `SQLite`, `udunits`) for spatial data analysis. This is the recommended setup for users working with spatial or GIS data on Midway3.

    **AMD Node Module:**
    - On Midway3 AMD nodes, there is a special module `R/4.3.2 (default)` built with the AMD Optimizing C/C++ Compiler (`aocc-4.1`). This module is found under `/software/modulefiles-amd` and is optimized for AMD hardware. Use this version for best performance on AMD compute nodes.

=== "Midway2"

    **Available R Versions:**

    - `R/2.15`
    - `R/3.0`
    - `R/3.2`
    - `R/3.3`
    - `R/3.3+intel-16.0` *(built with Intel 16 compiler)*
    - `R/3.4`
    - `R/3.4.1`
    - `R/3.4.3`
    - `R/3.5.1`
    - `R/3.6.1`
    - `R/3.6.3-no-openblas`
    - `R/4.0.0`
    - `R/4.0.4`
    - `R/4.1.0`
    - `R/4.1.0-no-openblas`
    - `R/4.2.0`

    ??? info "Build Details (click to expand)"
        - Most R modules are built with the system GCC compiler (`10.2.0` for recent versions; older modules may use earlier GCC or Intel compilers).
        - `R/3.3+intel-16.0` is built with the Intel 16 compiler.
        - `R/3.6.3-no-openblas` and `R/4.1.0-no-openblas` use the default BLAS (no OpenBLAS), which may reduce linear algebra performance.
        - Most modern modules (`R/4.1.0`, `R/4.2.0`) are built with `gcc/10.2.0`.
        - All modules are linked to OpenBLAS for improved matrix and linear algebra performance unless otherwise noted.
        - For exact dependencies and environment, use `ml show R/<version>`.

#### Spatial Packages

The `sf` package in R provides tools for handling spatial data using simple features. For more information, visit the [sf Package on CRAN](https://cran.r-project.org/web/packages/sf/index.html).
The `terra` and `raster` packages are also installed.

Midway2 Environment:

- **Dependencies**: GDAL 2.4.1, udunits 2.2
- **R Version**: 4.2.0

Midway3 Environment:

- **Dependencies**: GDAL 3.3.3, udunits 2.2, GEOS 3.9.1, GCC 10.2.0, SQLite 3.36.0
- **R Versions**: 4.2.1 and 4.3.1

Before using or installing `sf` on Midway3, load the necessary modules:
=== "Midway2"
    ```bash
    module load gdal/2.4.1 udunits/2.2 R/4.2.0
    ```
=== "Midway3"
    ```bash
    module load gdal/3.3.3 udunits/2.2 geos/3.9.1 gcc/10.2.0 sqlite/3.36.0 R/4.3.1
    ```

---

## Using R for High-Performance Computing (HPC)

You can run R scripts in batch mode using SLURM. Example job script:
```bash
#!/bin/bash
#SBATCH --job-name=my_r_job
#SBATCH --account=[your-accountname]
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00

module load R/4.3.1
Rscript my_script.R
```

??? note "Parallel R with MPI (Rmpi)"

    The `Rmpi` package is **not pre-installed** in system R modules. You must install it in your own R user library, and Rmpi must be compiled against the **same MPI implementation and version** you will use at runtime.

    **Example SLURM Batch Script for Rmpi Job:**
    ```bash
    #!/bin/bash
    #SBATCH --job-name=my_rmpi_job
    #SBATCH --account=[your-accountname]
    #SBATCH --partition=compute
    #SBATCH --nodes=1
    #SBATCH --ntasks=4
    #SBATCH --cpus-per-task=1
    #SBATCH --mem=16G
    #SBATCH --time=02:00:00

    module load R/4.3.1 openmpi/5.0.2  # Example: use any available OpenMPI version
    mpirun -np 4 Rscript my_rmpi_script.R
    ```

    **Step-by-step instructions:**
    1. **Load R and OpenMPI modules _before_ installing Rmpi:**
        ```bash
        module load R/4.3.1 openmpi/5.0.2  # Example: use any available OpenMPI version
        R
        ```
    2. **Install Rmpi from within R:**
        ```R
        install.packages("Rmpi", type = "source")
        ```
        You may be prompted for MPI library paths; the correct `openmpi` module must be loaded for detection.
    3. **Check installation:**
        ```R
        library(Rmpi)
        mpi.universe.size()
        ```
    4. **Important:** Always load the same `openmpi` module before running your parallel R jobs as you did when installing Rmpi.

    !!! tip "Other OpenMPI Versions"
        To see all installed OpenMPI versions, run:
        ```bash
        module avail openmpi
        ```

    !!! tip "Version Compatibility"
        - The `openmpi` version must match between installation and job execution.
        - If you change R or MPI module versions, reinstall `Rmpi` to match.

---

## Installing R Packages

R packages can be distributed as source code or compiled binaries. Source packages must be compiled before installation, typically requiring the GNU Compiler Collection (GCC). Here’s how to get started with R package installation on our HPC clusters.

#### Check GCC Version

To ensure compatibility, verify the version of GCC (g++) on your system:

```sh
$ g++ --version
g++ (GCC) 8.5.0 20210514 (Red Hat 8.5.0-10)
Copyright (C) 2018 Free Software Foundation, Inc.
This is free software; see the source for copying conditions.  There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
```

#### Before You Install

1. Check disk space:
   Ensure you have enough disk space using the `quota` command:
   ```sh
   $ quota
   ```

2. Load necessary modules:
   For packages like `ncdf4` and `hdf5r`, load the required modules before starting R:
   ```sh
   $ module load hdf5 netcdf
   ```
   For more information on working with netCDF files in R, you can check out this resource: [NetCDF with R](https://pjbartlein.github.io/REarthSysSci/netCDF.html). 


#### Installing Packages

To install R packages, use the `install.packages` function within an R session:

```R
install.packages("packageName")
```

For multiple packages:

```R
install.packages(c("package1", "package2"))
```

---


## Using the `renv` R Package to Create a Personal R Project Environment {#using-the-renv}

The `renv` package in R helps manage project-specific libraries, ensuring consistent package versions across projects. Here’s a step-by-step guide to set up and use `renv` for your project located at `/project/pi-cnetid/rproject/` on the Midway cluster.

#### Step 1: Load Necessary Modules

Before starting, ensure you have the necessary modules loaded. You can load the R module appropriate for your project:

```sh
module load R/4.3.1
```

#### Step 2: Set Up the Project Directory

Navigate to your project directory:

```sh
cd /project/pi-cnetid/rproject/
```

#### Step 3: Initialize `renv` in Your Project

Start R and initialize `renv` in your project directory:

```sh
R
```

Inside the R session, run:

```R
# Install renv if not already installed
install.packages("renv")

# Initialize renv in the project directory
renv::init()
```

This command will set up a new project-specific library in the `renv` subdirectory of your project directory and create an `renv.lock` file to record the state of your library.

#### Step 4: Install Packages within the `renv` Environment

With `renv` initialized, install any necessary packages:

```R
# Install required packages
renv::install("dplyr")
renv::install("ggplot2")
# Add more packages as needed
```

#### Step 5: Snapshot the Current State of Your Library

After installing the necessary packages, snapshot the current state of your library to `renv.lock`:

```R
renv::snapshot()
```

This records the exact versions of the packages you have installed, allowing you to recreate the environment later.

#### Step 6: Restore Library from `renv.lock` (Optional)

If you need to recreate the environment on another system or after a system change, you can restore the library:

```R
renv::restore()
```

This command reads the `renv.lock` file and installs the specified package versions.

#### Step 7: Using the Project

Whenever you start working on your project, load the `renv` environment:

```R
# Activate the renv environment
renv::activate()
```

This ensures that all package installations and library paths are managed by `renv`.

#### Example Workflow

Here’s a complete example workflow from the terminal to R session:

1. **Load R Module**:
   ```sh
   module load R/4.3.1
   cd /project/pi-cnetid/rproject/
   ```

2. **Start R and Initialize `renv`**:
   ```sh
   R
   ```

3. **Within R Session**:
   ```R
   install.packages("renv")
   renv::init()
   renv::install("dplyr")
   renv::install("ggplot2")
   renv::snapshot()
   q()  # Quit R session
   ```

4. **Future Sessions**:
   ```R
   renv::activate()
   ```

By following these steps, you can set up and manage a project-specific R environment on the Midway cluster, ensuring consistency and reproducibility for your R projects.

## Best Practices

### R modules
- Uses centrally maintained, optimized, and regularly updated R installations provided by HPC admins.
- Usually highly optimized (OpenBLAS).
- Integrates with system-wide libraries and supports `renv` for reproducibility.
- Recommended for most HPC users, especially for performance-critical or collaborative work.

### R via Conda
- Allows creation of isolated environments and user-space installation of R and dependencies.
- **Performance Caveat:** Conda R often does **not** use the highly optimized BLAS/LAPACK libraries available on the cluster, which can result in slower performance for linear algebra-intensive tasks.
- Use Conda R only if you need a specific version or package unavailable in system modules, or require full environment isolation.
- If using Conda R, you can still use `install.packages()` or `renv` within the environment, but be aware of possible compatibility and performance trade-offs.

| Feature/Aspect          | R Module (Midway)                       | Conda R                                 |
|------------------------|------------------------------------------|-----------------------------------------|
| BLAS/LAPACK Optimization | Usually highly optimized (OpenBLAS)     | Often default/less optimized BLAS       |
| Performance            | Best for heavy computation               | May be slower for matrix operations     |
| Integration            | Well-integrated with system libraries    | Isolated, may miss system optimizations |
| Reproducibility        | Use with `renv` or modules               | Use with `renv` or Conda YAML           |
| Use Case               | Recommended for most HPC users           | For custom/isolated needs only          |

---

## FAQ

1. How can I delete all R packages and start over?
   If you need to reset your R environment, delete all R packages and related files:
   ```sh
   $ rm -rf ~/R ~/.R ~/.rstudio* ~/.Rhistory ~/.Rprofile ~/.RData
   ```

2. How can I show the location where R packages are installed?
   ```R
   .libPaths()
   Sys.getenv("R_LIBS_USER")
   ```

3. How can I list the installed packages:
   ```R
   installed.packages()
   ```

4. How can I list the default packages?
   ```R
   getOption("defaultPackages")
   ```

5. How can I remove a package?
   ```R
   remove.packages("packageName")
   ```

6. How do I delete all R packages and start over?
   ```bash
   rm -rf ~/R ~/.R ~/.rstudio* ~/.Rhistory ~/.Rprofile ~/.RData
   ```

## Troubleshooting

| Issue          | Solution                       | 
|------------------------|------------------------------------------|
| Package installation fails due to missing system libraries | Load the necessary modules (e.g., `module load hdf5 netcdf`) before starting R     |
| R cannot find installed packages            | Check your `.libPaths()` in R and ensure you are using the correct environment/module               | 
| R job runs slowly            | Use the system R module for optimized BLAS/LAPACK performance. Avoid Conda R for heavy computations unless necessary   |
| Permissions or disk quota exceeded        | Check your disk space with `quota` and clean up files if needed.               |
