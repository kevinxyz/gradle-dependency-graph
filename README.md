# Gradle Dependency Graph Generator

The GDP generator consists of 2 phases. The first phase `create_gv_from_gradle.py` calls gradle to find out all the Gradle/Maven dependencies and generates Graphviz(.dot) files. The second phase `gv_to_svg.sh` takes .dot files and generates cilckable .svg images that look like something below:

![sample image](https://cloud.githubusercontent.com/assets/670053/23727309/602f88f8-040c-11e7-8277-f67c1ae6becf.png)

## Requirements

Below are the components that were tested against the most current version

* Python 2.7
* Gradle 3.0 or greater
* A gradle convention where:
    * There exists a `settings.gradle` file that contains something similar to the following:
```
    include('hello/project1-server',
               'hello/project2-server',
               ...)
    project(':hello/project1-server').name = 'hello-project1-server'
    project(':hello/project2-server').name = 'hello-project2-server'
    ...
```


## Sample usage

* Go to the top level code path where `settings.gradle` exists
* Type `create_gv_from_gradle.py --run-gradle` and wait for a while
* Type `gv_to_svg.sh`
* Try looking at the svg files (e.g. use your browser to point to the graphs)
