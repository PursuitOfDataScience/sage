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
			<p>A job is the Slurm&rsquo;s computing unit by which resources are allocated and shared. Users create job submission scripts to ask Slurm for resources such as cores, memory, walltime, etc. Slurm puts the requests in a queue and allocates requested resources based on jobs&rsquo; priority.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Compute cluster</td>
			<td dir="ltr">
			<p>A group of independent computers connected via a fast network interconnect, managed by a resource manage, and act as a large parallel computer. Each node in a cluster can be a shared memory parallel computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Compute node</td>
			<td dir="ltr">
			<p>A compute node is a stand-alone computer connected to other compute nodes via a fast network interconnect. A compute node is where a batch job runs and is not usually accessible directly by the users.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Core</td>
			<td dir="ltr">
			<p>Smallest computation unit that can run a program (used to be called a processor, still is, also called a CPU &ndash; Central Processing Unit).</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr">
			<p style="text-align:center">Distributed memory architecture</p>
			</td>
			<td dir="ltr">
			<p>Distributed memory architecture refers to a way to create a parallel computer. In this architecture, stand-alone compute nodes are connected using a fast interconnect such as Infiniband and exchange messages over the network.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">FLOPS</td>
			<td dir="ltr">
			<p>Floating point Operation Per Second (FLOPS) is a measure of computing performance in terms of number of floating operations that a CPU can perform per second. Modern CPUs are capable of doing Tera FLOPS (10^12 floating point operations per second).</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">GPU</td>
			<td dir="ltr">
			<p>Graphics Processing Unit (GPU) is a specialized device initially used to generate computer output. GPUs have their own memory but should be hosted in a node. Each compute node can host one or more GPUs. Modern GPUs have many simple compute cores and have been used for parallel processing.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">HPC</td>
			<td dir="ltr">
			<p>High Performance Computing (HPC) refers to the practice of aggregating computing power to achieve higher performance that would not possible by using a typical computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Infiniband</td>
			<td dir="ltr">
			<p>A computer network standard featuring high bandwidth and low latency. The current Infiniband devices are capable of transferring data at up to 100Gbits/sec with less than a microsecond latency. As of this writing, the popular Infiniband versions are FDR (Fourteen Data Rate) with 56Gbits/sec and EDR (Enhanced Data Rate) with 100Gbits/sec.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Job</td>
			<td>&nbsp;</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Login node</td>
			<td dir="ltr">
			<p>Login nodes (a.k.a. head nodes) are point of access to a parallel computer. Users usually connect to login nodes via SSH to compile and debug their code, review their results, do some simple tests, and submit their batch jobs to the parallel computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Modules</td>
			<td dir="ltr">
			<p>An open source software management tool used in most HPC facilities. Using modules enable users to selectively pick the software that they want and add them to their environment.</p>
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
			<p>Open Multi Processing (OpenMP) is a parallel programming model designed for shared memory architecture. In this programming mode, programmers insert compiler directives in their code and the compiler generates a code that can run on more than one core.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Partition</td>
			<td dir="ltr">
			<p>A subset of a compute cluster with a common feature. For example, compute nodes with GPU could form a partition.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr">
			<p style="text-align:center">Shared memory architecture</p>
			</td>
			<td dir="ltr">
			<p>Shared memory architecture is a way to create a parallel computer. In this architecture, a large memory is shared among many cores and communication between cores is done via the shared memory. By introducing the multi-core CPUs, each computer is a shared-memory parallel computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Slurm</td>
			<td dir="ltr">
			<p>Simple Linux Utility for Resource Management (SLURM) is a software that manages high performance computing resources. SLURM coordinates running of many programs on a shared facility and makes sure that resources are used in a fair share manner.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Socket</td>
			<td dir="ltr">
			<p>A computational unit, packaged as one and usually made of a single chip often called processor. Modern sockets carry many cores (2, 4 on most laptops, 8 to 16 on most servers).</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">SSH</td>
			<td dir="ltr">
			<p>Secure Shell (SSH) is a protocol to securely access remote computers. Based on the client-server model, multiple users with an SSH client can access to a remote computer. Some operating systems such as Linux and Mac OS have a built-in SSH client and others can use one of many publicly available clients.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr">
			<p style="text-align:center">Tightly-coupled nodes</p>
			</td>
			<td dir="ltr">
			<p>A set of compute nodes connected via fast Infiniband interconnect. These nodes can exchange data in a fast rate and are used to solve big problems that cannot fit in a single computer.</p>
			</td>
		</tr>
		<tr>
			<td dir="ltr" style="text-align:center">Walltime</td>
			<td dir="ltr">
			<p>The time that requires a program to finish execution.</p>
			</td>
		</tr>
	</tbody>
</table>

