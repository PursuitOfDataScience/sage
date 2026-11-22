# Software

## R: CRAN Repository

An offline snapshot of CRAN is available at `repos = "file:///software/sdeCRAN"`.

For example, to install `dplyr`:

```R

install.packages("dplyr", repos = "file:///software/sdeCRAN", type = "source", dependencies = TRUE)
```

