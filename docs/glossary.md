# Glossary

Welcome to the RCC Glossary, your go-to guide for understanding the key terms in high-performance computing (HPC). Let's demystify the world of clusters, nodes, and parallel processing!

<table align="center" border="1" cellpadding="0" cellspacing="0">
	<thead>
	</thead>
	<tbody>
		<tr>
			<td dir="ltr" style="text-align:center"><strong>Term</strong></td>
			<td dir="ltr" style="text-align:center"><strong>Meaning</strong></td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Batch job</td>
			<td dir="ltr">
			<p>A batch job is a job that runs non-interactively from a job submission script. Users create job submission scripts to ask Slurm for resources such as cores, memory, wall time, etc. Slurm puts the requests in a queue and allocates the requested resources based on the jobs&rsquo; priority.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Compute cluster</td>
			<td dir="ltr">
			<p>A group of independent computers connected via a fast network interconnect and managed by a resource manager, acting as a large parallel computer. Each node in a cluster can be a shared memory parallel computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Compute node</td>
			<td dir="ltr">
			<p>A compute node is a stand-alone computer connected to other compute nodes via a fast network interconnect. A compute node is where a batch job runs and is not usually directly accessible to users.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Core</td>
			<td dir="ltr">
			<p>The smallest computation unit that can run a program (also called a processor or a CPU &ndash; Central Processing Unit).</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr">
			<p style="text-align:center">Distributed memory architecture</p>
			</td>
			<td dir="ltr">
			<p>Distributed memory architecture refers to a way to create a parallel computer. In this architecture, stand-alone compute nodes are connected using a fast interconnect such as InfiniBand and exchange messages over the network.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">FLOPS</td>
			<td dir="ltr">
			<p>Floating-point Operations Per Second (FLOPS) is a measure of computing performance in terms of the number of floating-point operations that a processor can perform per second. Modern CPUs are capable of teraFLOPS (10^12 floating-point operations per second).</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">GPU</td>
			<td dir="ltr">
			<p>A Graphics Processing Unit (GPU) is a specialized device originally designed to generate graphics output. GPUs have their own memory but must be hosted in a node. Each compute node can host one or more GPUs. Modern GPUs have many simple compute cores and are widely used for parallel processing.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">HPC</td>
			<td dir="ltr">
			<p>High-Performance Computing (HPC) refers to the practice of aggregating computing power to achieve performance that would not be possible with a typical computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">InfiniBand</td>
			<td dir="ltr">
			<p>A computer network standard featuring high bandwidth and low latency, with sub-microsecond latency. Common InfiniBand versions include FDR (Fourteen Data Rate) at 56 Gbit/s, EDR (Enhanced Data Rate) at 100 Gbit/s, and HDR (High Data Rate) at 200 Gbit/s.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Job</td>
			<td dir="ltr">
			<p>A job is Slurm&rsquo;s unit of work, to which computing resources are allocated. A job can be a batch job or an interactive job.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Login node</td>
			<td dir="ltr">
			<p>Login nodes (a.k.a. head nodes) are the points of access to a parallel computer. Users usually connect to login nodes via SSH to compile and debug their code, review their results, do some simple tests, and submit their batch jobs to the parallel computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Modules</td>
			<td dir="ltr">
			<p>An open-source software management tool used in most HPC facilities. Modules enable users to selectively pick the software that they want and add it to their environment.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Node</td>
			<td dir="ltr">
			<p>A stand-alone computer system that contains one or more sockets, memory, storage, etc. connected to other nodes via a fast network interconnect.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">OpenMP</td>
			<td dir="ltr">
			<p>Open Multi Processing (OpenMP) is a parallel programming model designed for shared memory architecture. In this programming model, programmers insert compiler directives in their code, and the compiler generates code that can run on more than one core.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Partition</td>
			<td dir="ltr">
			<p>A subset of a compute cluster with a common feature. For example, compute nodes with GPUs could form a partition.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr">
			<p style="text-align:center">Shared memory architecture</p>
			</td>
			<td dir="ltr">
			<p>Shared memory architecture is a way to create a parallel computer. In this architecture, a large memory is shared among many cores and communication between cores is done via the shared memory. With the introduction of multicore CPUs, every computer is now a shared-memory parallel computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Slurm</td>
			<td dir="ltr">
			<p>Slurm (originally Simple Linux Utility for Resource Management) is software that manages high-performance computing resources. Slurm coordinates the running of many programs on a shared facility and makes sure that resources are shared fairly.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Socket</td>
			<td dir="ltr">
			<p>A computational unit, packaged as one and usually made of a single chip often called a processor. Modern sockets carry many cores (typically 4 to 16 on laptops, and dozens on servers).</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">SSH</td>
			<td dir="ltr">
			<p>Secure Shell (SSH) is a protocol to securely access remote computers. Based on the client-server model, multiple users with an SSH client can access a remote computer. Some operating systems such as Linux and macOS have a built-in SSH client, and others can use one of many publicly available clients.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr">
			<p style="text-align:center">Tightly coupled nodes</p>
			</td>
			<td dir="ltr">
			<p>A set of compute nodes connected via a fast InfiniBand interconnect. These nodes can exchange data at a fast rate and are used to solve big problems that cannot fit in a single computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Wall time</td>
			<td dir="ltr">
			<p>The elapsed real-world time a program takes to finish execution. In Slurm, the wall time limit (<code>--time</code>) is the maximum time a job is allowed to run.</p>

			</td>
		</tr>
	</tbody>
</table>

