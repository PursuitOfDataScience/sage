# Gaussian

<a href='https://gaussian.com/gaussian16/' target='_blank'>Gaussian</a> is a general-purpose computational chemistry software package with focus on electronic structure modeling. Gaussian is developed and licensed by Gaussian, Inc.

## Getting access

<p align='center'>
<img src='../../../img/software/gaussian-access.png'
width='650'
alt='A flowchart of steps for accessing Gaussian through the RCC. These steps are detailed below.'
longdesc='TXT'/>
</p>

**Step 1** If you are not already an RCC user, your first step is to become one. If you are a Principal Investigator (PI), submit a <a href='https://rcc.uchicago.edu/accounts-allocations/pi-account-request' target='_blank'>PI Account Request</a>. If you are a student, postdoc, staff member, etc., submit a <a href='https://rcc.uchicago.edu/accounts-allocations/general-user-account-request' target='_blank'>General User Account Request</a>.

**Step 2** To access Gaussian, you must be a member of the RCC's `gaussian` Unix group. You can check if you are already a member of the `gaussian` group by running `groups` in the terminal while connected to a Midway cluster login node. To join the `gaussian` group, submit a <a href='https://rcc.uchicago.edu/accounts-allocations/general-user-account-request' target='_blank'>General User Account Request</a> with "Gaussian" as the Principal Investigator account name. (Note that even PIs submit a General User Account Request to get access to Gaussian. This is different from Step 1, where PIs submit a PI Account Request to become an RCC user.)

Once you are a member of the `gaussian` group, you will be able to run Gaussian programs. To check what versions of Gaussian are currently available on the Midway clusters, use SSH to log into Midway2 or Midway3 and run this command in your terminal:

```
$ module avail gaussian
```

The versions of Gaussian on Midway2 and Midway3 may be different; please check both ecosystems if you need a specific version of Gaussian.

You can run Gaussian jobs in an [`sinteractive` session](../../slurm/sinteractive.md), meaning you connect live to a compute node, or by using an [`sbatch` script](../../slurm/sbatch.md) to send your job to a compute node. (Gaussian jobs only run on compute nodes, not login nodes.) See below for examples of each of these workflows.

## Example Gaussian job with `sinteractive`
You can start an `sinteractive` session on Midway3 by running this command in your terminal. Don't forget to replace `pi-drpepper` with your account (typically your PI's CNetID).

```
$ sinteractive --partition=caslake --account=pi-drpepper --nodes=1 --ntasks-per-node=8 --mem-per-cpu=16000 --time=00:30:00
```

Next, load Gaussian by running this command in your terminal. Substitute `16RevA.03` with whichever version of Gaussian you would like to use. (Remember you can see available versions of Gaussian by running `module avail gaussian` in your terminal.)

```
$ module load gaussian/16RevA.03
```

Now you can run Gaussian with the `g#` command. Match `#` to whatever version of Gaussian you have loaded: `g16` for `16RevA.03`, `g09` for `gaussian09`, etc. For example, this code uses `16RevA.03` to run a file called `your-input.com` and write the results to `your-output.out`:

```
$ g16 < your-input.com > your-output.out
```

If you need to make more complex specifications, use an `sbatch` file (see below) to submit your job to the RCC's [Slurm workload manager](../../slurm/main.md), which will run the job on a compute node for you.

## Example Gaussian job with `sbatch`

Here is an example input file, `water.com`:

```
%mem=16GB
%nprocshared=8
# HF/6-31G(d)

water energy

0   1
O  -0.464   0.177   0.0
H  -0.464   1.137   0.0
H   0.441  -0.143   0.0
```

Here is an example `sbatch` file, `water.sbatch`, that runs `water.com`:

```
#!/bin/bash
#SBATCH --job-name=example_sbatch_gaussian
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --account=rcc-staff # replace this with your PI account 
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16000 # in Megabytes
#SBATCH --error=example.err 

module load gaussian/16RevA.03

g16 < water.com > $SLURM_JOB_ID.out

touch $SLURM_JOB_ID.txt 
echo "Job ID: $SLURM_JOB_ID" >> $SLURM_JOB_ID.txt 
echo "Job name: $SLURM_JOB_NAME" >> $SLURM_JOB_ID.txt
echo "N tasks: $SLURM_ARRAY_TASK_COUNT" >> $SLURM_JOB_ID.txt
echo "N cores: $SLURM_CPUS_ON_NODE" >> $SLURM_JOB_ID.txt
echo "N threads per core: $SLURM_THREADS_PER_CORE" >> $SLURM_JOB_ID.txt
echo "Minimum memory required per CPU: $SLURM_MEM_PER_CPU" >> $SLURM_JOB_ID.txt
echo "Requested memory per GPU: $SLURM_MEM_PER_GPU" >> $SLURM_JOB_ID.txt
```

Gaussian can consume a lot of memory, so include these additional flags in your `sbatch` file if you are running a large job:

```
#SBATCH –exclusive # The job allocation can not share nodes with other running jobs 
#SBATCH –mem=0 # Use the maximum available memory on the node
```

You can submit this example job by running this command in your terminal:

```
sbatch water.sbatch
```

For calculations that involve multiple steps (such as geometry optimization, single-point calculation, frequency analysis), it is recommended to generate and update <a href='https://gaussian.com/man/' target='_blank'>checkpoints</a> during individual steps (via the `%Chk` command). The checkpoint of the preceding steps will be loaded for the following steps (via the `%OldChk` command). This way, if the job crashes or is terminated due to time limit, you can resubmit the job at the suitable step to continue the calculation. For more details and guidelines, please refer to the <a href='https://gaussian.com/man/' target='_blank'>Gaussian documentation</a>.

## Input and output

GaussianView is a graphical interface used with Gaussian. It aids in the creation of Gaussian input files, enables the user to run Gaussian calculations from a graphical interface without the need for using a command line instruction, and helps in the interpretation of Gaussian output. Users can use it to plot properties, animate vibrations, or visualize computed spectra.

You can use GaussianView on Midway2 with:

```
module load gaussian/09RevB.01
```

However, GaussianView is not currently available for any of the versions of Gaussian on Midway3.

To use GaussianView, you will need to run and X server on your computer and enable [X11 forwarding](../../connection/ssh/main.md) when you log into the cluster. Otherwise, users need to open a ThinLinc session to open the GaussianView GUI.

Other options to prepare the molecular structure used in the input files include software packages such as <a href='https://avogadro.cc/' target='_blank'>Avogadro</a>, a molecule editor and visualizer. Avogadro is also available on Midway2.

Alternatively, users can use <a href='https://molview.org/' target='_blank'>MolView</a> (a web-based application), or <a href='https://www.chemcraftprog.com/' target='_blank'>ChemCraft</a> (a cross-platform application). After generating the molecular structure from these packages, users put the atom coordinates into  the Gaussian input file, or use another tool to assemble a proper input file.

Gaussian output can be visualized using Avogadro, VMD or OVITO. Users can check the installed versions of these software packages on Midway2 and Midway3 via the `module avail` command.


### GPU support
On Midway3, the module `gaussian/16RevC.02` supports GPU acceleration with NVIDIA Tesla A100 GPUs. To run Gaussian with GPU support, please refer to the <a href='https://gaussian.com/gpu/'>Gaussian</a> documentation.

An example of the job script to use GPU is given below.

```
#!/bin/bash
#SBATCH --account=rcc-staff   # replace this with your PI account 
#SBATCH -t 02:00:00
#SBATCH --nodes=1
#SBATCH --partition=gpu
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32GB            # replace this with the memory on the CPU side
#SBATCH --gres=gpu:1
#SBATCH --constraint=a100

module load gaussian/16RevC.02

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export MP_BIND=yes

# form the MP_BLIST variable from the allocated threads
#export MP_BLIST=0,1,2,3,4,5,6,7

last=$(( OMP_NUM_THREADS-1 ))
export MP_BLIST=`seq -s , 0 $last`
echo $MP_BLIST

# set the scratch space for gaussian temp data, which is by default the submitting dir
# export GAUSS_SCRDIR=/scratch/midway3/$USER

# launch the run
g16 < input.txt > output.txt
```

This job script requests 1 node, 1 task per node, 8 CPU cores for multithreading, and 32 GB RAM. It also request 1 GPU on the node.

The input file `input.txt` should contain the following settings:

```
%cpu=0-7
%gpucpu=0=0
%mem=32GB
```

to indicate that the CPU cores with indices from 0 through 7 will be used for the calculation, and the GPU 0 will be driven by CPU core 0.

## Additional resources
HPC Wiki: <a href='https://hpc-wiki.info/hpc/Gaussian'>Gaussian</a>  
Central Washington University: <a href='https://kb.ndsu.edu/135576' target='_blank'>Running Gaussian on Linux</a>  
North Dakota State University: <a href='https://www.youtube.com/watch?v=Zh4tbqVCHWg'>Running Gaussian 16 on CCAST Clusters</a>   












