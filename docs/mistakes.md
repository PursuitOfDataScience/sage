# Common Mistakes to Avoid

Mistakes happen, but with a little know-how, you can steer clear of common pitfalls that might trip you up on your RCC journey. Here's what to watch out for: 

1. **Don't Overstuff Your Storage:** Do not go over your storage quota.<br> Going over your storage quota can spell trouble, leading to job failures, cryptic error messages, and X11 forwarding woes. Keep tabs on your usage with the `quota` command and avoid unnecessary headaches. Learn more about what to do if you find yourself over quota in the [Storage FAQ](storage/faq.md).
 
2. **Beware of Conda Environments:** Do not install conda environments using `conda create --name=<env_name>`.<br> 
Installing conda environments in the wrong directory can quickly eat up precious storage space. By default, this command installs a conda environment into your `/home` directory, which has a low quota. Because conda environments often require a large amount of storage and a large number of files, this can easily result in exceeding your quota. Instead, install environments inside the `/project` or `/project2` directories by running `conda create --prefix=/project/<PI_CNetID>/<CNetID>/anaconda/<env_name>`. See [Python](software/apps-and-envs/python.md) for more details.

1. **Do not run jobs on the login nodes.**<br> 
The login nodes are for quick tasks, not heavy lifting. Save the computational heavyweights for the Slurm job scheduler, or risk getting your account benched. When you connect to a cluster via SSH, you land on the login node, which all users share. The login node is reserved for submitting jobs, compiling codes, installing software, and running short tests that use only a few CPU cores and finish within a few minutes. Anything more intensive must be submitted to the Slurm job scheduler as either a batch or interactive job. Failure to comply with this rule may result in your account being temporarily suspended.
 
1. **Stay Offline in Jobs:** Do not try to access the Internet from batch or interactive jobs.<br> 
Jobs submitted to Slurm don't have Internet access. All jobs submitted to the Slurm job scheduler, including interactive sessions started from ThinLinc, run on compute nodes without Internet access. Because of this, a running job cannot download files, install packages, or connect to GitHub. Plan ahead and perform any necessary downloads or installations on the login node before you submit the job.
 
1. **One Core is Enough for Serial Jobs:** Do not allocate more than one CPU core for serial jobs.<br> 
Don't waste precious service units by allocating more CPU cores than you need for serial jobs. Serial codes cannot run in parallel, so using more than one CPU core will not cause the job to run faster. Instead, doing so will waste SUs allocated to your PI. Visit the Batch jobs page of the user guide to learn about [job arrays](slurm/sbatch.md#job-arrays), which are a convenient way to submit a large number of independent processing jobs, and run [parallel batch jobs](slurm/sbatch.md#parallel-batch-jobs).
 
1. **Scale Up Responsibly:** Do not run jobs with a parallel code without conducting a scaling analysis.<br>
Before diving into parallel computing, make sure you've done your scaling analysis. If your code runs in parallel, you need to determine the optimal number of nodes and CPU cores. The same is true if it can use multiple GPUs.
 
1. **GPU for GPU Codes Only:** Do not request a GPU for a code that can only use CPUs. Only codes explicitly written to use GPUs can take advantage of GPUs.<br> 
Don't hog the GPUs unless your code can actually put them to good use. Allocating resources you don't need only slows things down for everyone else. Allocating a GPU for a CPU-only code will not speed up the execution time, but it will increase your queue time, waste resources, and lower the priority of your next job submission. Furthermore, some codes are written to use only a single GPU.
 
1. **Keep Your GCC Up-to-Date:** Do not use the system GCC when a newer version is needed.<br>
Don't let outdated tools hold you back. If you need a newer version of GCC, load it up and keep your development environment cutting-edge. The GNU Compiler Collection (GCC) provides a suite of compilers (gcc, g++, gfortran) and related tools. You can determine the version of the system GCC by running the command `gcc --version`. If the system version is insufficient, load the appropriate environment module to make a newer version available; run `module avail gcc` to see the available versions. Learn more about environment modules in the [Software](software/index.md) section of the user guide.
 
1. **Name That Module:** Do not load environment modules using only the partial name.<br>
When loading environment modules, be specific. Don't leave it to chance—use the full name to avoid any surprises down the line. A common practice for Python users is to issue the `module load python` command. You should always specify the full name of the environment module (e.g., `module load python/miniforge-25.3.0`) in case the default version changes. Also, you should avoid loading environment modules in your `~/.bashrc` file. Instead, do this in Slurm scripts and on the command line when needed.
 
1. **Mind Your Scratch:** Do not write temporary files to `/scratch` if your job has high-throughput I/O.<br>
If your job deals with lots of small files, think twice about dumping them in `/scratch`. Consider your options and choose wisely to optimize performance. Temporary files may accumulate and exceed your quota (both in size and/or number of files) unless removed on time. If your job is not distributed across multiple nodes and has high-throughput I/O of many small files (size < 4 MB), it may run faster if you write temporary files to local rather than global scratch. You can learn about different types of scratch and when to use them in the [Storage](storage/main.md#scratch-space) section of the user guide.

1. **Build Smart:** Do not compile and install heavy software on login nodes.<br>
Heavy software installations belong in the build partition, not on the login nodes. Keep the system humming along smoothly by following the rules of the road. Sometimes software installation time can be dramatically reduced by using multiple cores. However, compute-intensive jobs are not permitted on login nodes and may be killed to provide equal opportunities for other connected users. Instead of login nodes, use a build partition dedicated to software installation.

By sidestepping these common missteps, you'll be on the fast track to success in no time. Happy computing!