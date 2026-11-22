# Geospatial Analysis on Midway3

This guide explains how to set up an environment for geospatial analysis on the Midway3 cluster at the University of Chicago. It is divided into sections that detail the steps for connecting to the cluster and using software and containers relevant to geospatial analysis.

### Section I: Connecting to Midway Cluster

#### 1. GUI-based Access
For geovisualization, a GUI-based approach is preferred. [ThinLinc](../../connection/thinlinc/main.md) is recommended due to its seamless working environment, which supports features like a shared clipboard. ThinLinc can be accessed in two ways:

- **ThinLinc Client**: Download and install the ThinLinc client from the [ThinLinc download page](https://www.cendio.com/thinlinc/download). It is available for all major operating systems.
- **Web Access**: You can also access ThinLinc through a browser by navigating to `https://midway3.rcc.uchicago.edu`. This method does not require any client installation.

#### 2. Command Line Access and X Forwarding
For users who prefer or require command-line access, especially for scripting and automation:

- **Using SSH with X Forwarding**:
    - **Xshell and VcXsrv** (Windows): Xshell is free for academic and home use and has a smaller memory footprint than other tools like MobaXterm. However, it requires the installation of an X11 server such as Xming or VcXsrv.
    - Connect via SSH with X forwarding enabled:
      ```
      ssh -Y <user>@midway3.rcc.uchicago.edu
      ```
      Replace `<user>` with your actual username on the Midway3 cluster.

### Section II: Software

#### 1. Using Software Packages
Key geospatial libraries and tools are available on Midway3, including GDAL for geospatial data manipulation and analysis, as well as spatial libraries for R and Python:

- **For R**:
  - Load the R module and start R:
    ```
    module load R
    R
    ```
- **For Python**:
  - Python and its libraries can be accessed via the Python modules, which support virtual environments (see [Python](../../software/apps-and-envs/python.md)):
    ```
    module load python
    source activate <env_name>
    ```

#### 2. Loading QGIS
QGIS can be loaded and used directly on Midway3 by activating the appropriate Python environment and loading the software module:
```
module load python
source activate qgis
qgis
```

#### 3. Using Containers
Containers provide a reproducible environment for more complex or customized setups. Singularity is used on Midway3 to manage containers:

- **How to Use Singularity**:
  - Load the Singularity module and interact with a container:
    ```
    ml singularity
    singularity shell -B $HOME/code:<mount_point> -B $SCRATCH/$USER:/data <image_path>
    ```
    For example, to load an OTBTF (Orfeo Toolbox with TensorFlow) image:
    ```
    singularity shell -B $HOME/code/cook -B $SCRATCH/$USER:/data otbtf_6.3.1-cpu.sif
    ```

If you build or pull large images, redirect Singularity's temporary and cache directories away from `/tmp` (see [Apptainer & Singularity](../../software/apps-and-envs/singularity.md#known-issues)):

```
export SINGULARITY_TMPDIR=$SCRATCH/$USER/container/faketmp
export SINGULARITY_CACHEDIR=$SCRATCH/$USER/container/fakecache
```

This guide covers the basic setup for geospatial analysis on Midway3. Depending on specific project requirements, additional configurations or software packages might be necessary.
