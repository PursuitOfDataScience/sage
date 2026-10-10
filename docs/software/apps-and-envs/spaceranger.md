# Space Ranger
Spaceranger is a set of analysis pipelines that process Visium Spatial Gene Expression data with brightfield and fluorescence microscope images.
[Spaceranger Manual](https://support.10xgenomics.com/spatial-gene-expression/software/pipelines/latest/what-is-space-ranger)

### Installation
The spaceranger comes as a binary that does not require compiling. Use Firefox in ThinLinc to download the [software](https://www.10xgenomics.com/support/software/space-ranger/downloads). You may create a folder called 'software' in your home or project directory and extract it to that location. Change pi-cnetid with the the group name. if using for personal purpose, you can use scratch storage available at `$SCRATCH/$USER` folder.
Change the extraction location to `/project/pi-cnetid/software`, or somewhere else and use the following command:

```bash
tar -xzvf spaceranger-3.0.0.tar.gz --directory /project/pi-cnetid/software
```

#### Updating PATH

After extracting the software, update the PATH as follows:

**Update PATH:**

```bash
export PATH=/project/pi-cnetid/software/spaceranger-3.0.0:$PATH
```

**Save in .bashrc:**
Command above will change the $PATH temporarily only for that bash shell. You can permanently update the PATH by appending the following command to the .bashrc file:

```bash
echo 'export PATH=/project/pi-cnetid/software/spaceranger-3.0.0:$PATH' >> ~/.bashrc
```

These commands will ensure that `spaceranger-3.0.0` is extracted to the specified location and added to the PATH for permanent access as discussed [here](https://www.10xgenomics.com/support/software/space-ranger/downloads/space-ranger-installation)

Docker [image](https://hub.docker.com/r/cumulusprod/spaceranger/tags) can be executed using Apptainer.

- [Tutorials](https://www.10xgenomics.com/support/software/space-ranger/latest/tutorials)

- [Job Submission Mode](https://www.10xgenomics.com/support/software/space-ranger/latest/advanced/job-submission-mode)

- [Space Ranger Cluster Mode](https://www.10xgenomics.com/support/software/space-ranger/latest/advanced/cluster-mode)
