# KICP Tutorial

!!! Note
    This page was migrated from the previous user guide with minimal editing. Some details may now be out of date. See the main sections of this guide for the most up-to-date content. 

The KICP has exclusive access to a number of compute nodes associated with the RCC
Midway cluster.  KICP users access those nodes through the same login nodes and
interfaces as the primary cluster, making it trivial to move computational work
between the two sets of resources. Most of the documentation available on this site is applicable to KICP members and the KICP nodes, however there are some specific differences which are described here.

Email sent to [kicp@rcc.uchicago.edu](mailto:kicp@rcc.uchicago.edu){:target='_blank'} will be assigned a trouble ticket and reviewed
by the RCC Help Desk.  Please don’t hesitate to ask questions if
you encounter any issues, or have any requests for software installation.

## Get an account

Please complete the RCC [User Account Request](https://rcc.uchicago.edu/general-user-account-request){:target='_blank'} form to request an account and put KICP as
the PI (note: this request will be reviewed for KICP membership).  Please clearly state your
connection to the KICP, particularly if you are not a local or senior member.  If you are
requesting access for someone not at the University of Chicago (i.e. someone who doesn’t have
a CNetID), the account creation process will involve creating a CNetID.

To access the rest of the Midway cluster you will need to be added to a different account
than KICP, typically provided by a faculty member acting as PI. All KICP faculty are eligible
to act as PI for themselves and others, and many already have PI accounts on the Midway cluster.

## Submit A Job

As a shared resource, Midway uses a batch queueing system to allocate nodes to individuals
and their jobs.  Midway uses the [Slurm](http://slurm.schedmd.com){:target='_blank'} batch queuing system, which is similar to the possibly
more familiar PBS batch system.

Please see the Midway2 and Midway3 HPC Systems section of this User Guide for information on using Midway to perform
computational tasks, typically by submitting batch jobs. The [Slurm](http://slurm.schedmd.com){:target='_blank'} commands, reiterated below, can be used as described in that documentation, however KICP users may need to point to one of the
two KICP partitions, kicp and kicp-ht, and select the kicp account.

**NOTE**: Specifying –account=kicp and –partition=kicp is generally optional for users who belong to
the KICP group and no other, however specifying them is generally good practice.

| Useful Commands        | Description                                                   |
|------------------------|---------------------------------------------------------------|
| sbatch -p kicp -a kicp | Submit a job to the Slurm scheduling system.                  |
| sinteractive -p kicp   | Run an interactive job on a KICP compute node                 |
| squeue -p kicp         | List the submitted and running jobs in the KICP partition.    |
| squeue -u $USER        | List the current users’ own submitted and running jobs.       |
| sinfo -p kicp          | List the number of available and allocated KICP nodes.        |
| scancel job_id         | Cancel the job identified by the given job_id (e.g. 3636950). |
| scancel -u $USER       | Cancel all jobs submitted by the current user                 |


There are many ways to submit a batch job, depending on what that job requires (number of
processors, number of nodes, etc). Slurm will automatically start your job in the directory
from which it was submitted.  To submit a job, create a batch script, say my_job.sh and submit
with the command sbatch my_job.sh.  The following is a list of commonly used sbatch commands.  A
more complete list can be found in the sbatch man page.

The following is a good example batch script:

```default
#!/bin/bash

#SBATCH --job-name=my_job
#SBATCH --output=my_job_%j.out
#SBATCH --time=24:00:00
#SBATCH --partition=kicp
#SBATCH --account=kicp
#SBATCH --nodes=1
#SBATCH --exclusive

echo $SLURM_JOB_ID starting execution `date` on `hostname`

# load required modules (change to your requirements!)
# example: module load openmpi/1.8

# uncomment below if your code uses OpenMP to properly set the number of threads
# export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# the commands to run your job
# example: mpirun ./my_task
# Note: slurm will automatically tell MPI how many tasks and tasks per node to use
```

### KICP Queues

KICP has the access to the following queues (partition in Slurm terminology):

| Partition | Wallclock limit | Job limits                     |
|-----------|-----------------|--------------------------------|
| kicp      | 48h             | 256 cores, 64 jobs per user    |
| kicp-ht   | 36h             | 64 cores/job, 32 jobs per user |
| kicp-long | 100h            | 128 cores/queue, 64 cores/user |


access to kicp-long requires special authorization.

If you are running jobs with significant I/O or communication between nodes (typically MPI jobs),
then you should use the the tightly-coupled, infiniband nodes accessed through the kicp and kicp-long
partitions. Purely serial or embarrassingly parallel jobs with a large calculation to I/O ratio (say MCMC
likelihood sampling) should use the high-throughput nodes in the kicp-ht queue.  The limits for kicp-ht
were relaxed to encourage use.  If users start to conflict, they may be restricted to prevent
a single user from dominating those nodes.

Midway also includes two large memory (256GB) and four GPU enabled nodes, as well as a significantly larger
set of nodes that are shared with the rest of the University.  Accessing these resources requires a separate
allocation.  Please contact the RCC for more details.

## Storage

Your home directory has a 30G quota,
and should be used for small files and codes.

KICP has a 50TB allocation in `/project/kicp/`, and each user is initially given a 1TB quota and their
own subdirectory (`/project/kicp/$USER)`. If you require more space, please let the RCC know and
your quota may be increased on a case-by-case basis.

New project space is no longer allocated under /project but under /project2.

Both home and project space are backed up hourly
to disk, and daily to tape.

Finally, there is a high-performance filesystem mounted on /scratch/midway2 which should be used during runs and
has a 5TB quota. This
directory is not backed up and should not be used for long-term storage. In future, files older than a to be
determined age may be removed automatically, so please practice good data management.

### Snapshots and Backups

We all inadvertently delete or overwrite files from time to time.  Snapshots are automated backups that
are accessible through a separate path.  Snapshots of a user’s home directory can be found in
`/snapshots/\*/home/*cnetid*/` where the subdirectories refer to the frequency and time of
the backup, e.g. daily-2012-10-04.06h15 or hourly-2012-10-09.11h00.

## Software

Many common astrophysical codes and libraries have been installed or built on Midway. Other common astrophysics packages require configuration at compilation that prevent them from being installed system-side. Look here for program specific compilation flags, installation instructions, etc for these packages.
Please contact the RCC if you notice any problems with any of the software or instructions.

### IDL

IDL is installed on Midway, however the RCC is unable to provide licenses to the entire community. Users who have their own licenses or license servers may configure them to be able to use IDL on Midway’s login and compute nodes. Contact RCC for more details.

### CosmoMC

CosmoMC is a Markov-Chain Monte-Carlo (MCMC) code which is integrated with the theoretical power spectrum code CAMB.  Since
it is often modified by users, we don’t install a system-wide version, however we have verified that the following parameters
give good performance (Warning: under construction, don’t use these instructions without first talking to the RCC).

Specific installation instructions for a non-mpi build using the intel compiler and the intel math kernel library mkl 10.3
(note, these differ slightly from those provided by the CosmoMC readme ):

* Download CosmoMC from cosmologist.info and untar on Midway


* Load the modules appropriate for the compiler you intend to use.  In this case a non-mpi build with the intel compiler: `module load intel/12.1 cfitsio/3+intel-12.1 mkl/10.3`


* Edit the CosmoMC Makefile located in the source subdirectory

The WMAP7 likelihood code and data are already configured and installed on Midway in the `/project/kicp/opt/WMAP/` directory.
The stock v4 and v4p1 versions from Lambda  are installed, as is a patched version of v4 with special optimizations from
Cora Dvorkin & Wayne Hu.  Select the version you wish to use and change the WMAP variable to point to the full directory, e.g.
`WMAP = /project/kicp/opt/WMAP/likelihood_v4p1`.


* Modify the compiler and optimization options

```bash
F90C = ifort
FFLAGS = -O2 -openmp -fpp
LAPACKL = $(MKLROOT)/lib/intel64/libmkl_lapack95_lp64.a \
              -Wl,--start-group \
              $(MKLROOT)/lib/intel64/libmkl_intel_lp64.a \
              $(MKLROOT)/lib/intel64/libmkl_sequential.a \
              $(MKLROOT)/lib/intel64/libmkl_core.a \
              -Wl,--end-group -lpthread
```


* Run make

Note, this section is under construction.  Updated build instructions for a variety of compilers and mpi support will come soon.

### ART

ART has default compilation flags for Midway.  Set the environment variable PLATFORM to midway. This platform file will automatically detect
the MPI environment and compiler option you are using and configure the code accordingly.

### RAMSES

Ramses is a cosmological hydrodynamic adaptive mesh refinement code originally written by Romain Teyssier.  It is public, and can be
downloaded .  Oscar Agertz has compiled and run Ramses on Midway and reports good performance with the following makefile configuration:

```bash
F90 = mpif90 -O3
FFLAGS = -cpp -DNVAR=$(NVAR) -DNDIM=$(NDIM) -DNPRE=$(NPRE) \
            -DSOLVER$(SOLVER) -DNOSYSTEM -DNVECTOR=$(NVECTOR)
LIBMPI =
LIBS = $(LIBMPI)
```

### Gadget

This refers to the public version of Gadget 2.0.7. The following Makefile configuration should work under all combination of compilers, MPI libraries, and Gadget options (including HDF5 support):

```bash
CC = mpicc
OPTIMIZE = -O3
MPICHLIB =
HDF5INCL = -DH5_USE_16_API
HDF5LIB = -lhdf5
```

The code requires that modules are loaded for fftw2, gsl, mpi, and an optional hdf5.  Make sure to load compiler and MPI library specific versions of the modules as necessary.  Some examples are given below:


* Intel compiler + Intel MPI (note, loading intelmpi will automatically load intel/12.1):

```bash
module load intelmpi/4.0+intel-12.1 fftw2/2.1.5+intelmpi-4.0+intel-12.1 hdf5/1.8 gsl/1.15
```


* Intel compiler + OpenMPI:

```bash
module load openmpi/1.6+intel-12.1 fftw2/2.1.5+openmpi-1.6+intel-12.1 hdf5/1.8 gsl/1.15
```


* GCC + OpenMPI:

```bash
module load openmpi/1.6 fftw2/2.1.5+openmpi-1.6 hdf5/1.8 gsl/1.15
```




## Automating Large Numbers of Tasks

Researchers often need to perform a number of calculations
that vary only in their initial conditions or input parameters.
Such tasks naturally arise when exploring the predictions of a
model over a range of parameters or when testing a numerical
calculation for convergence. Automating these tasks is critical,
both for computational efficiency and to minimize human error and
ensure the calculation is reproducible.

This tutorial will discuss a number of techniques and tools
available on Midway for automating the running of tasks and
their respective advantages and disadvantages. In particular
we will focus on those tasks which are entirely
independent of each other and where the total number of tasks
is known (and fixed).

When deciding between the various techniques, users should
consider the following:

* overhead or cost of starting each task (including cost of starting remote processes)
* waiting time each batch job will spend in the queue
* total number of jobs compared to available resources and limits
* the average calculation time per job and its variance
* the cost in developer time needed for a given solution

As a semi-realistic example, this tutorial will use the CLASS
code to compute the non-linear matter power specturm for a range
of the neutrino parameter N_eff.

### CLASS and classy

[CLASS](http://class-code.net/){:target='_blank'} [[1104.2932](http://arxiv.org/abs/1104.2932){:target='_blank'}] is a Boltzmann code similar
to CMBFAST, CAMB, and others. It can be used to compute a number of large-scale
structure and CMB observables and since it is designed to perform calculations
within MCMC-type likelihood analyses, it is a good option for these exercises.

To install **CLASS** and its Python wrapper, **classy**, use the
following commands:

```bash
module load git python/2.7-2014q3
git clone https://github.com/lesgourg/class_public
cd class_public
make
```

**NOTE**: This will install the Class python wrappers in your .local directory
while remembering where you compiled CLASS. Make sure you delete them
both after completing the exercises.

[classy](https://github.com/lesgourg/class_public/wiki/Python-wrapper){:target='_blank'}
is a Python wrapper for the CLASS code which we will use for convenience.
It allows us to avoid the common issue of dealing with parameter files.

The code that uses classy to compute the non-linear matter power spectrum
for a given N_eff is as follows:

```python
#!/bin/env python

def compute_pk(N_eff=3.04, output="pk.dat"):
    import numpy as np
    from classy import Class

    # initialize Class with default parameters save N_eff
    c = Class()
    c.set({'output':'mPk', 'non linear':'halofit', 'N_eff':N_eff})
    c.compute()
    with open(output, "w") as output:
        for k in np.logspace(-3., 0.5, 100):
            print >>output, "%.6e %.6e" % (k, c.pk(k, z=0.0))
    c.struct_cleanup()

    # if necessary for visualization, add a 5 second delay
    #import time; time.sleep(5)

# perform work associated with i out of N steps
def work(i, N=100):
    N_eff_min = 2.5
    N_eff_max = 4.5
    N_eff = (N_eff_max-N_eff_min)*float(i)/float(N) + N_eff_min
    output = "pk_{}.dat".format(i)
    compute_pk(N_eff, output)

# collect the resulting matter power spectra and plot 
def plot_pk(file_pattern="pk_*.dat",output="pk.png"):
    import pylab, glob
    import numpy as np

    f = pylab.figure(figsize=(5,5))
    for data in glob.glob(file_pattern):
        (k, pk) = np.loadtxt(data, unpack=True)
        f.gca().loglog(k, pk, color='k', alpha=0.05)
    f.gca().set_xlabel("k [Mpc/h]")
    f.gca().set_ylabel("P(k)")
    f.tight_layout()
    f.savefig(output)

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        work(int(sys.argv[1]), int(sys.argv[2]))
    else:
        plot_pk()

    print "done"
```

Run this code without any input parameters to generate the following png figure
from the resulting output files.


#### Parallel Programming

Implementing your own parallel scheme is useful when the tasks are not completely
independent, or represent only a part of a larger, non-trivial workflow. Calculations
that rely on large pre-calculated tables or have costly initilization may also benefit
from an explicit scheme, as those costs can be amortized over a larger number of tasks.

### Multiprocessing

Smaller numbers of tasks can be divided amongst workers on a single node. In high
level languages like Python, or in lower level languages using threading language
constructs such as OpenMP, this can be accomplished with little more effort than a
serial loop. This example also demonstrates using Python as the script interpreter
for a Slurm batch script, however note that since Slurm copies and executes batch
scripts from a private directory, it is necessary to manually add the runtime
directory to the Python search path.

```python
#!/bin/env python

#SBATCH --job-name=multiprocess
#SBATCH --output=logs/multiprocess_%j.out
#SBATCH --time=01:00:00
#SBATCH --partition=kicp
#SBATCH --account=kicp
#SBATCH --nodes=1
#SBATCH --exclusive

import multiprocessing
import sys
import os

# necessary to add cwd to path when script run 
# by slurm (since it executes a copy)
sys.path.append(os.getcwd()) 
from pk import work

# get number of cpus available to job
try:
    ncpus = int(os.environ["SLURM_JOB_CPUS_PER_NODE"])
except KeyError:
    ncpus = multiprocessing.cpu_count()

# create pool of ncpus workers
p = multiprocessing.Pool(ncpus)

# apply work function in parallel
p.map(work, range(100))
```

### MPI

Process and threaded level parallelism is limited to a single machine.

```python
#!/bin/env python

#SBATCH --job-name=mpi
#SBATCH --output=logs/mpi_%j.out
#SBATCH --time=01:00:00
#SBATCH --partition=kicp
#SBATCH --ntasks=100

from mpi4py import MPI
from pk import work

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

work(rank, size)
```

MPI programs and Python scripts must be launched using **mpirun** as shown
in this Slurm batch script:

```bash
#!/bin/bash

#SBATCH --job-name=mpi
#SBATCH --output=logs/mpi_%j.out
#SBATCH --time=01:00:00
#SBATCH --partition=kicp
#SBATCH --account=kicp
#SBATCH --ntasks=100

module load mpi4py/1.3-2014q3+intelmpi-4.0

mpirun python mpi_pk.py
```

In this case we are only using MPI as a mechanism to remotely launch tasks on distributed
nodes. All processes must start and end at the same time, which can lead to waste
of resources if some job steps take longer than others.

#### Job Scheduler

Most of this workshop will focus on using various features of Midway’s batch scheduler,
[Slurm](http://slurm.schedmd.com){:target='_blank'} as its sole purpose is to help organize batch job submission.

### Slurm task per job

In some cases it may be easiest to wrap the job submission in a
script or bash command, taking advantage of the fact that Slurm
will pass on environment variables defined at the time of job
submission (this is also why you can load modules before submitting
a job rather than inside the job script itself).

```bash
for i in {0..10}; do export i; sbatch job.sbatch; done
```

```bash
#!/bin/bash

#SBATCH --job-name=job
#SBATCH --output=logs/job_%j.out
#SBATCH --time=01:00:00
#SBATCH --partition=kicp
#SBATCH --account=kicp
#SBATCH --ntasks=1

python pk.py $i 100
```

**NOTE**: It can be difficult to monitor and jobs submitted in this way. Be sure to use a unique
job-name so you can identify a particular job group with commands like **squeue** and **scancel**,
e.g. `scancel -n class`

### GNU Parallel

<a href='http://www.gnu.org/software/parallel/' target='_blank'>GNU Parallel</a> is a tool for executing tasks in parallel, typically on a single machine. When coupled with the <a href='http://slurm.schedmd.com' target='_blank'>Slurm</a> command **srun**, **parallel** becomes a powerful way
of distributing a set of tasks amongst a number of workers. This is particularly useful when
the number of tasks is significantly larger than the number of available workers (Slurm’s
`--ntasks`).

```bash
#!/bin/sh

#SBATCH --time=01:00:00
#SBATCH --output=logs/parallel.log
#SBATCH --partition=kicp
#SBATCH --account=kicp
#SBATCH --ntasks=32
#SBATCH --exclusive

module load parallel

# the --exclusive to srun makes srun use distinct CPUs for each job step
# -N1 -n1 allocates a single core to each task
srun="srun --exclusive -N1 -n1"

# --delay .2 prevents overloading the controlling node
# -j is the number of tasks parallel runs so we set it to $SLURM_NTASKS
# --joblog makes parallel create a log of tasks that it has already run
# --resume makes parallel use the joblog to resume from where it has left off
# the combination of --joblog and --resume allow jobs to be resubmitted if
# necessary and continue from where they left off
parallel="parallel --delay .2 -j $SLURM_NTASKS --joblog logs/runtask.log --resume"

# this runs the parallel command we want
# in this case, we are running a script named runtask
# parallel uses ::: to separate options. Here {0..99} is a shell expansion
# so parallel will run the command passing the numbers 0 through 99
# via argument {1}
$parallel "$srun python pk.py {1} 100 > logs/parallel_{1}.log" ::: {0..99}

```

This job is submitted as with any [Slurm](http://slurm.schedmd.com){:target='_blank'} batch job

```bash
$ sbatch parallel.sbatch
```

and will appear as a single job in the queue, assigned as many nodes/cores as was requested:

```bash
$ squeue -u $USER -p kicp
   JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)
11511073      kicp parallel    drudd  R       0:00      2 midway[203,390]
```

GNU Parallel maintains a log of the work that has already been done, along with the exit
value of each step (useful for determining any failed steps).

```bash
$ head logs/runtask.log
Seq Host    Starttime   Runtime Send    Receive Exitval Signal  Command
1   :   1422211597.529  6.467   0   0   0   0   srun --exclusive -N1 -n1 python pk.py 0 100 > logs/runtask.0
2   :   1422211597.732  6.466   0   0   0   0   srun --exclusive -N1 -n1 python pk.py 1 100 > logs/runtask.1
3   :   1422211597.935  6.466   0   0   0   0   srun --exclusive -N1 -n1 python pk.py 2 100 > logs/runtask.2
4   :   1422211598.138  6.464   0   0   0   0   srun --exclusive -N1 -n1 python pk.py 3 100 > logs/runtask.3
```

In our case we requested the output from each work step be directed to a file **logs/runtask.{1}**,
allowing us to perform further diagnostics if necessary. The parallel option `--resume` creates a file
**parallel.log** which allows GNU Parallel to resume a job that has been stopped due to failure or by hitting
a walltime limit before all tasks have been completed. If you need to rerun a GNU Parallel job, be sure
to delete **parallel.log** or it will think it has already finished!

**NOTE**: More information may found in the RCC documentation section [Parallel batch jobs](../slurm/sbatch.md#parallel-batch-jobs).

### Slurm Job Array

Most HPC job schedulers support a special class of batch job known as array jobs (or job arrays). <a href='http://slurm.schedmd.com' target='_blank'>Slurm</a> support for job arrays is relatively new and is undergoing active development. The GNU Parallel solution in the previous section was developed at RCC because of the former lack of <a href='http://slurm.schedmd.com' target='_blank'>Slurm</a> array jobs.

An example <a href='http://slurm.schedmd.com' target='_blank'>Slurm</a> array job submission script is as follows:

```bash
#!/bin/bash

#SBATCH --job-name=array
#SBATCH --output=logs/array_%A_%a.out
#SBATCH --array=0-99
#SBATCH --time=01:00:00
#SBATCH --partition=kicp
#SBATCH --account=kicp
#SBATCH --ntasks=1

# the environment variable SLURM_ARRAY_TASK_ID contains
# the index corresponding to the current job step
python pk.py $SLURM_ARRAY_TASK_ID 100
```

This looks very similar to our single-job batch submission script, but with the addition
of the `--array` feature. In this case, the `--array=0-99` will cause 100
individual array-tasks to be created when this job script is submitted. Each array task
is a copy of the master script, with an environment variable called `SLURM_ARRAY_TASK_ID`
set to the index of the array task. As with the GNU Parallel example, we simply pass the
value of that environment variable into our program to perform that piece of work.

Each array job will enter the queue and run when resources are available for it, as if we had
submitted each job manually (this is merely a highly-convenient shortcut).

Array job indices do not need to be a linear range, and can be specified in a number of ways.  For example:

```default
A job array with index values of 1, 2, 5, 19, 27:
#SBATCH --array=1,2,5,19,27

A job array with index values between 1 and 7 with a step size of 2 (i.e. 1, 3, 5, 7):
#SBATCH --array=1-7:2
```

The `%A_%a` construct in the output and error file names is used to generate unique output and error files
based on the master job ID (%A) and the array-tasks ID (%a).  In this fashion, each array-task will be able to
write to its own output and error files.

When we submit a job array, we will see the master process, as well as any submitted, running or otherwise
not completed array tasks with the naming convention `%A_%a`.

```bash
$ squeue
           JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)
11510950_[10-99]      kicp    array    drudd PD       0:00      1 (None)
      11510950_0      kicp    array    drudd  R       0:00      1 midway185
      11510950_1      kicp    array    drudd  R       0:00      1 midway185
      11510950_2      kicp    array    drudd  R       0:00      1 midway185
      11510950_3      kicp    array    drudd  R       0:00      1 midway185
      11510950_4      kicp    array    drudd  R       0:00      1 midway185
      11510950_5      kicp    array    drudd  R       0:00      1 midway185
      11510950_6      kicp    array    drudd  R       0:00      1 midway185
      11510950_7      kicp    array    drudd  R       0:00      1 midway185
      11510950_8      kicp    array    drudd  R       0:00      1 midway185
      11510950_9      kicp    array    drudd  R       0:00      1 midway185
```

We can cancel all array tasks associated with the master job ID as before, or cancel any subset of them using
the naming convention `%A_%a`

```bash
# cancel job steps 10-100
$ scancel 11510950_[10-100]

# cancel all remaining job steps
$ scancel 11510950
```

What happens if we try to submit a job with, say, `--array=0-1000`?

```bash
sbatch: error: Batch job submission failed: Job violates accounting/QOS policy (job submit limit, user's size and/or time limits)
```

The number of jobs a user may have submitted (not running!) at any given time is limited, in order to
avoid overloading the scheduler and to ensure users cannot accidentally swamp the machines with malformed
job submissions. To see how many jobs can be run or submitted for a given partition+QOS, use the following
command:

```bash
$ sacctmgr list qos kicp format=maxjobsperuser, maxsubmitjobsperuser
MaxJobsPU MaxSubmitPU
--------- -----------
       64         128
```

The ability to submit array jobs which are larger than `MaxSubmitPU` is coming in a newer
version of [Slurm](http://slurm.schedmd.com){:target='_blank'}. Until then, each job should handle more than one piece of work, or the GNU Parallel
solution should be used. For more information, see the RCC documentation section [Job arrays](../slurm/sbatch.md#Job-arrays).

#### Workflow Tools

Other specialized tools have been created for handling parallel workflows, particularly in specific
domains or for specific analysis or computational codes. Developing such tools is an open area of
research.
