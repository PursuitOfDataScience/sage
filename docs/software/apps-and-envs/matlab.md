# MATLAB

RCC provides the Matlab programming environment on all Midway compute resources.  Most Matlab toolboxes are also available (see: [https://itservices.uchicago.edu/page/matlab-tah-toolboxes](https://itservices.uchicago.edu/page/matlab-tah-toolboxes)).  When running compute- or memory-intensive Matlab jobs on Midway, it is important to run on compute nodes, and not on the login nodes.

!!! note
    Compute- and memory-intensive jobs running on the login nodes are subject to termination without warning by RCC system administrators as this impacts the performance of the login nodes and ability for other users to work.

## Getting Started

To gain access to Matlab, a Matlab module must be loaded with the command:

```bash
module load matlab
```

A full list of the available Matlab versions can be obtained by issuing the command:

```bash
module avail matlab
```

## Using Matlab’s Textual Interface

On Midway, Matlab can be launched at the terminal with the commands:

```bash
module load matlab
matlab
```

This will launch Matlab’s textual interface. We recommend running Matlab on a compute node as opposed to a login node. 

## Using Matlab’s GUI Interface

To use Matlab’s GUI interface on Midway, we recommend connecting to Midway via ThinLinc. 

Note that once connected via ThinLinc, you will be accessing a Midway login node.  In order to run Matlab with its GUI interface on a compute node, obtain a terminal in the ThinLinc desktop and issue the **sinteractive** command.  This will deliver you to a compute node.  From there, you can launch Matlab with the command:

```bash
module load matlab
matlab
```

and have access to the GUI interface.

## Running Matlab Jobs with SLURM

To submit Matlab jobs to Midway’s resource scheduler, SLURM, the Matlab commands to be executed must be contained in a single .m script.

`matlab_simple.m` is a basic Matlab script that computes and prints a 10x10 magic square

`matlab_simple.sbatch` is a submission script that submits Matlab program to the default queue

To run this example, download both files to a directory on Midway.  Then, enter the following command to submit the program matlab_simple.m to the scheduler:

```bash
sbatch matlab_simple.sbatch
```

Output from this example can be found in the file named matlab.out which will be created in the same directory.

## Matlab Parallel

To run MATLAB effectively using parallel computing techniques requires a few
basic concepts which can be optimized and expanded upon.  The MATLAB Parallel
Computing Toolbox User’s Guide is the official documentation and should be
referred to for further details, examples and explanations.  Here, we provide
some Midway-specific considerations that RCC users should be aware of.

RCC recommends MATLAB 2014b for parallel matlab computing as it relaxes the restriction on number of workers available through the PCT.

**NOTE**: At this time, RCC does not support the Matlab Distributed Compute Server (MDCS).  As such, parallel Matlab jobs are limited to a single node with the “local” pool through use of the Parallel Compute Toolbox (PCT). 

### Basic PCT Operation

The most basic level of parallelization in Matlab is achieved through use of a `parfor` loop in place of a `for` loop.  The iterations of a `parfor` loop are distributed to the workers in the active matlabpool and computed concurrently.  For this reason, care must be taken to ensure that each iteration of the parfor loop is independent of every other.

The overall procedure for leveraging parfor in your Matlab script is as follows:


1. Create a local matlabpool


2. Call `parfor` in place of `for` in your Matlab scripts and functions

A simple Matlab script that uses parfor can be downloaded here: `matlab_parfor.m` and is shown below.

```bash
% start the matlabpool with maximum available workers
% control how many workers by setting ntasks in your sbatch script
pc = parcluster('local')
parpool(pc, str2num(getenv('SLURM_CPUS_ON_NODE')))

% run a parfor loop, distributing the iterations to the SLURM_CPUS_ON_NODE workers
parfor i = 1:100

        ones(10,10)

end
```

### Submitting a PCT Matlab Job to SLURM

Compute intensive jobs that will consume non-trivial amounts of CPU and/or memory resources should not be run on Midway’s login nodes.  Instead, the job should be submitted to the scheduler and run on a compute node.  A sample submission script for the above example Matlab sample is provided here: `matlab_parfor.sbatch` and is shown below.

```bash
#!/bin/bash

#SBATCH --job-name=whatever
#SBATCH --output=matlab_parfor.out
#SBATCH --error=matlab_parfor.err
#SBATCH --partition=sandyb
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=16

module load matlab/2014b

matlab -nodisplay < matlab_parfor.m

```

### Running Multiple PCT Matlab Jobs

Specific care must be taken when running multiple PCT jobs on Midway.  When you submit multiple jobs that are all using PCT for parallelization, the multiple matlabpools that get created have the ability to interfere with one another which can lead to errors and early termination of your scripts.

The Matlab PCT requires a temporary “Job Storage Location” where is stores information about the Matlab pool that is in use.  This is simply a directory on the filesystem that Matlab writes various files to in order to coordinate the parallelization of the matlabpool.  By default, this information is stored in /home/YourUsername/.matlab/ (the default “Job Storage Location”).  When submitting multiple jobs to SLURM that will all use the PCT, all of the jobs will attempt to use this default location for storing job information thereby creating a race condition where one job modifies the files that were put in place by another.  Clearly, this situation must be avoided.

The solution is to have each of your jobs that will use the PCT set a unique location for storing job information.  To do this, a temporary directory must be created before launching matlab in your submission script and then the matlabpool must be created to explicitly use this unique temporary directory.  An example sbatch script `matlab_multi.sbatch` to do this is shown below:

```bash
#!/bin/bash

#SBATCH --job-name=whatever
#SBATCH --output=matlab_parfor.out
#SBATCH --error=matlab_parfor.err
#SBATCH --partition=sandyb
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=16

module load matlab/2014b

# Create a temporary directory on scratch
mkdir -p $SCRATCH/$SLURM_JOB_ID

# Kick off matlab
matlab -nodisplay < multi_parfor.m 

# Cleanup local work directory
rm -rf $SCRATCH/$SLURM_JOB_ID

```

And the corresponding Matlab script `multi_parfor.m` shown here:

```bash

% create a local cluster object
pc = parcluster('local')

% explicitly set the JobStorageLocation to the temp directory that was created in your sbatch script
pc.JobStorageLocation = strcat(getenv('SCRATCH'),'/', getenv('SLURM_JOB_ID'))

% start the matlabpool with maximum available workers
% control how many workers by setting ntasks in your sbatch script
parpool(pc, str2num(getenv('SLURM_CPUS_ON_NODE')))

% run a parallel for loop
parfor i = 1:100
    ones(10,10)
end
```
