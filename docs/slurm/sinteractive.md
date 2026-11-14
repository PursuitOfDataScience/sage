# Interactive jobs
Interactive jobs are the most intuitive way to use RCC clusters, as they allow you to interact with the program running on compute node/s (e.g., execute cells in a Jupyter Notebook) in real-time. This is great for exploratory work or troubleshooting. An interactive job will persist until you disconnect from the compute node or until you reach the maximum requested time.  

To request an interactive job with default parameters, run the following command while connected to a login node:  

```
sinteractive -A [pi-account] -p [partition] -N [# of nodes] --ntasks-per-node=[# of tasks] --time=[time]
```

!!! note
    On Midway3, you **always** need to specify the account to be charged for the job explicitly. Slurm will use the default partition (Midway2: `broadwl`, Midway3: `caslake`) if you do not specify it.

!!! note
    On Midway3, to use the partitions with AMD CPUs, it is recommended that you log in to the `midway3-amd.rcc.uchicago.edu` login node and submit jobs from this login node. 

!!! note 
	By default, an interactive session times out after ***2 hours***. If you would like more than 2 hours, include a `--time=HH:MM:SS` flag to specify the necessary amount of time. 

As soon as the requested resources become available, `sinteractive` will do the following: 
 
1. Log in to the compute node/s in the requested partition.  
2. Change into the directory you were working in.  
3. Set up X11 forwarding for displaying graphics.  
4. Transfer your shell environment, including any previously loaded modules.  

There are many additional options for the sinteractive command, including options to select the number of nodes, the number of cores per node, the amount of memory, and so on. For example, to request exclusive use of two compute nodes on the default CPU partition for 8 hours, enter the following:

=== "Midway2"
    ```
    sinteractive --exclusive --partition=broadwl --nodes=2 --time=08:00:00
    ```
===+ "Midway3"
    ```
    sinteractive --account=pi-<PI's CNETID> --exclusive --partition=caslake --nodes=2 --time=08:00:00
    ```
For more details about these and other useful parameters, check [Slurm `sbatch` page](./sbatch.md).

!!! tip
    All options in the `sbatch` command are also available for the `sinteractive` command. 

### Debug QoS 
There is a debug QOS (Quality of Service) setup to help users quickly access some resources to debug or test their code before submitting their jobs to the main partition. The debug QoS will allow you to run one job and get up to four cores for 15 minutes without consuming SUs. To use the debug QoS, specify `--time` as 15 minutes or less. For example, to get two cores for 15 minutes, you could run:

```
sinteractive --qos=debug --time=00:15:00 --ntasks=2 --account=pi-<PI CNETID>
```
You can find out the available `qos` for your account with the command `rcchelp`

```
rcchelp qos
```

Additionally, it is important to use the `--mem` or `--mem-per-cpu` options. For example, to request 8 CPU cores and 128 GB of memory on a bigmem2 node, add the following to your `.sbatch` script:

```bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
```

These same options can also be used to set up a sinteractive session. For example, on Midway3 to access a `bigmem` node with 1 CPU and 128 GB of memory, run: 

```bash
sinteractive --partition=bigmem --ntasks=1 --cpus-per-task=8 --mem=128G --account=pi-<PI CNETID>
```


Once you are connected to the compute node where the interactive session is runnnig, you can load python:
```
module load python
```

and run `python`

```
[your-cnetid@midway3-0xyz ] python
Python 3.9.19 | packaged by conda-forge | (main, Mar 20 2024, 12:50:21) 
[GCC 12.3.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>>
```

After quitting `python`, you can activate the environment you created, and list the installed packages

```
source /project/[pi-folder]/[your-cnetid]/my-venv/bin/activate
pip list
```
You should see `numpy`, `matplotlib` and `pandas` installed in this environment.

Let us prepare a simple Python script, namely, `simple.py` with a text editor like `nano`, in the current folder, with the following content:

```
import numpy as np
from matplotlib import pyplot as plt 
x = np.arange(1,11) 
y = 2 * x + 5 
plt.title("Matplotlib demo") 
plt.xlabel("x axis caption") 
plt.ylabel("y axis caption") 
plt.plot(x,y)
plt.savefig("output.pdf", format="pdf")
```
And run it with 

```
python simple.py
```

which should produce a file `output.pdf`.

Change to the input data folder
```
cd /project/[pi-folder]/[your-cnetid]/lammps/examples
```

Load the same modules you used to build LAMMPS (except `cmake`)

```
module load mpich/3.4.3+gcc-10.2.0 mkl/2023.1
```

Relax the locked memory limit
```
ulimit -l unlimited
```

Run the LAMMPS binary you built above
```
mpirun -np 8 /project/[pi-folder]/[your-cnetid]/lammps/build/lmp -in melt/in.melt
```

The run will produce the LAMMPS screen output and a file named `log.lammps` in the current folder.

### Monitoring an interactive session

While your session is running, you can watch its CPU, memory, and GPU usage live with [`slurmwatch`](https://github.com/PursuitOfDataScience/slurmwatch). Because an interactive session uses a single shell, run it in a second pane on the **same compute node** (for example, with `tmux`) so it watches your work without getting in the way:

```
module load slurmwatch
tmux            # open a second pane, then:
slurmwatch      # in one pane; run your program in the other
```

It watches the whole job, so it keeps reporting as you run one program, edit your code, and run another — there is no need to restart it between runs. Running it on the node reads usage directly and adds no extra Slurm step, so it will not interfere with your `srun`/`mpirun` launches. See [Monitoring running jobs](./sbatch.md#monitoring-running-jobs) for more.

To terminate the interactive session, run

```
exit
```

You will get back to the login node.