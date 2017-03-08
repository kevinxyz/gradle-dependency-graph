#!/usr/bin/env python
#
# For the most up to date version, please see:
# https://github.com/kevinxyz/gradle-dependency-graph
#
import copy
import json
import multiprocessing
from optparse import OptionParser
import os
import re
import shutil
import subprocess
import sys
import time
import threading

PARSER = OptionParser()
PARSER.add_option('--run-gradle', dest='run_gradle',
                  default=False,
                  action='store_true',
                  help='Execute gradle dependencies')
PARSER.add_option('--deprecated-node-re', dest='deprecated_node_re',
                  default='deprecated|old',
                  help='Regular expression to match deprecated node')
PARSER.add_option('--node-separator', dest='node_sep',
                  default=0.1,
                  help='Node separator. Bigger means more spaces in between nodes')

GRADLE_DEP_CMD='gradle dependencies --configuration {configuration} --project-dir {proj_dir}'
CACHE_FILE = './.gradle.dependency.cache'
OUTPUT_PATH = './gradle_graphs'
COLOR_CONTAINER = '#98FB98'  # '#30F27B'  #'lightgreen'

#NODE_DEPRECATED_RE = 'deprecated'
NODE_DEPRECATED_COLOR = 'pink'
NODE_POJO_RE = 'pojo'
NODE_POJO_COLOR = '#98FB98'  # lightgreen
NODE_COMMON_RE = 'common'
NODE_COMMON_COLOR = '#FFBB22'  # orange
NODE_COMMONENDPOINT_RE = '^common\-'
NODE_COMMONENDPOINT_COLOR = '#FF9900'  # orange

LINK_ALREADYDEFINED_COLOR = '#FF8888'
LINK_UNIMPORTANT_RE = 'slf4j|log4j'
LINK_UNIMPORTANT_COLOR = '#DDDDDD'

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)  # stdout flush


class GradleThread(threading.Thread):
    def __init__(self, thread_count, configuration, module_path_list, output, lock):
        threading.Thread.__init__(self)
        self.thread_count = thread_count
        self.gradle_config = configuration
        self.module_path_list = module_path_list
        self.output = output
        self.lock = lock

    def run(self):
        while self.module_path_list:
            time.sleep(0.25)
            with self.lock:
                if not self.module_path_list:
                    return
                module_path = self.module_path_list.pop()

            module_name, path = module_path
            cmd = GRADLE_DEP_CMD.format(configuration=self.gradle_config, proj_dir=path)
            print '[%d]$ %s' % (self.thread_count, cmd)
            proc = subprocess.Popen(cmd.split(' '), stdout=subprocess.PIPE, )
            stdout_value = proc.communicate()[0]
            return_code = proc.returncode
            if return_code != 0:
                print('[%d] Unable to perform %s, skipping...' %
                      (self.thread_count, cmd))
                continue
            with self.lock:
                self.output.append([module_name, path, stdout_value])


class Node(object):
    def __init__(self, name):
        self.name = name
        self.children = {}  # child_name to Node mapping

    def add_child(self, child):
        assert(isinstance(child, Node))
        self.children[child.name] = child

    def grandchild_exists(self, child_name):
        for child in self.children.itervalues():
            if child.child_exists(child_name):
                return True
        return False

    def child_exists(self, child_name):
        if child_name in self.children:
            return True
        return self.grandchild_exists(child_name)


def clean_node(node):
    return re.sub('\W', '_', node)


def grandchild_node_exists(parent_node_name, grandchild_node_name, dot_relationship):
    global _DOT_RELATIONSHIP, _NODENAME2NODE
    if dot_relationship != _DOT_RELATIONSHIP:
        _NODENAME2NODE = {}
        for from_name, to_name in dot_relationship:
            for node_name in (from_name, to_name):
                if node_name not in _NODENAME2NODE:
                    _NODENAME2NODE[node_name] = Node(node_name)
            from_node = _NODENAME2NODE[from_name]
            to_node = _NODENAME2NODE[to_name]
            from_node.add_child(to_node)
        _DOT_RELATIONSHIP = dot_relationship

    return _NODENAME2NODE[parent_node_name].grandchild_exists(grandchild_node_name)


_NODENAME2NODE = {}
_DOT_RELATIONSHIP = set()  # (from_name, to_name) relationships


def create_dot(gradle_config, filename, dot_relationship, owned_component, options):
    augmented_dot_relationship = copy.copy(dot_relationship)
    node_described = set()

    def generate_node(wd, node, style):
        if node in node_described:
            return
        node_described.add(node)

        if re.search(' \-\> ', node, re.I):
           #style = ',bold'
           color = 'color="red",fillcolor="#CCCCCC"'
        else:
           color = ''

        if node in owned_component:
            if re.search(NODE_DEPRECATED_RE, node, re.I):
                color = 'fillcolor="%s"' % NODE_DEPRECATED_COLOR
            elif re.search(NODE_POJO_RE, node, re.I):
                color = 'fillcolor="%s"' % NODE_POJO_COLOR
            elif re.search(NODE_COMMONENDPOINT_RE, node, re.I):
                color = 'color="black",fillcolor="%s"' % NODE_COMMONENDPOINT_COLOR
            elif re.search(NODE_COMMON_RE, node, re.I):
                color = 'fillcolor="%s"' % NODE_COMMON_COLOR
            else:
                color = 'colorscheme=blues9, fillcolor=4'

            if re.search(NODE_COMMONENDPOINT_RE, node, re.I):
                style = ',bold'

            wd.write('    {node}'
                     ' [label="{label}", fontsize=12,'
                     ' style="filled,rounded{style}", shape=box,'
                     ' {color},'
                     ' URL="./{label}.{gradle_config}.svg"];\n'.format(
                gradle_config=gradle_config,
                node=clean_node(node),
                color=color,
                style=style,
                label=node))
        else:
            if re.search(NODE_COMMON_RE, node, re.I):
                color = ',color="black",fillcolor="%s"' % NODE_COMMON_COLOR
            m = re.search('(.+):([\w\.\[\(\]\)\ ,]+)\s*\->\s*([\w\.]+)', node)
            if m:
                node_label = '%s->%s' % (m.group(2), m.group(3))
            else:
                node_label = node
            wd.write('    {node}'
                     ' [label="{label}", '
                     'style="filled,rounded{style}"{color}, shape=box];\n'.format(
                node=clean_node(node),
                label=node_label,
                style=style,
                color=color))

    def generate_edge(_from, _to):
        #try:
        has_grandchild_node = grandchild_node_exists(_from, _to,
                                                     augmented_dot_relationship)
        #except KeyError, e:
        #    print 'Unable to find: %s' % e
        #    has_grandchild_node = False
        edge_color = 'black'
        penwidth = 0.7
        if re.search(LINK_UNIMPORTANT_RE, _to, re.I):
            edge_color = LINK_UNIMPORTANT_COLOR
        elif has_grandchild_node:
            edge_color = LINK_ALREADYDEFINED_COLOR
        label = ''
        if _from in owned_component and _to in owned_component:
            if re.search(LINK_UNIMPORTANT_RE, _to, re.I):
                edge_color = LINK_UNIMPORTANT_COLOR
            elif (re.search('pojo', _from, re.I) and
                      not re.search(NODE_COMMON_RE, _to, re.I)):
                edge_color = 'red'  # pojo should ONLY point to common
            elif re.search(NODE_COMMON_RE, _to, re.I):
                penwidth = 1.2
            wd.write('    {_from} -> {_to} ['
                     ' arrowsize=0.60,'
                     ' penwidth={penwidth},'
                     ' color="{edge_color}"'
                     '{label}]; \n'.format(
                _from=clean_node(_from),
                _to=clean_node(_to),
                penwidth=penwidth,
                edge_color=edge_color,
                label=label))
        else:
            wd.write('    {_from} -> {_to} ['
                     'size=1,color="{edge_color}"{label}]; \n'.format(
                _from=clean_node(_from),
                _to=clean_node(_to),
                edge_color=edge_color,
                label=label))

    # --- write into file ---
    for from_to in (copy.copy(dot_relationship)):
        _from, _to = from_to
        # Expand the node: something:1.9.3 -> 1.11.54
        m = re.search('(.+):([\w\.\[\(\]\)\ ,]+)\s*\->\s*([\w\.]+)', _to)
        if not m:
            continue
        plain_node, version_from, version_to = m.group(1, 2, 3)
        _from, _to = _to, '%s:%s' % (plain_node, version_to)
        augmented_dot_relationship.add((_from, _to))

    with open(filename, 'w') as wd:
        wd.write('''digraph GGG {{
    rankdir=LR;
    graph [nodesep="{node_sep}",fontsize=8];
    node[fontsize=10,margin=0.02,height=0.12,color="#CCCCCC"];
    edge[fontsize=8, penwidth=0.7, arrowsize=0.40, color=gray];'''.format(
            node_sep=options.node_sep
        ))
        # wd.write('    {rank=same %s}' % ' '.join(sorted(map(clean_node, owned_component))))

        for from_to in sorted(augmented_dot_relationship):
            _from, _to = from_to

            style = ''

            # generate node information
            generate_node(wd, _from, style)
            generate_node(wd, _to, style)

            # generate edge
            generate_edge(_from, _to)
        wd.write('\n}\n')


def generate_dot_files(gradleconfig2modulepath_outputs, options):

    def _generate_dot_files(gradle_config, module_path_outputs):
        all_dot_relationships = set()
        owned_component = set()
        for _mout in module_path_outputs:
            module_name, path, outputs = _mout
            output = outputs.split('\n')
            print "Processing %s (%s), %d lines" % (module_name, path, len(output))
            idx = 0
            hierarchy = []
            dot_relationship = set()

            while idx <= len(output) - 1:
                line = output[idx]
                #print line
                m = re.search('^Project\s+:([\w\-\.]+)', line)
                if m:
                    project_name = m.group(1)
                    hierarchy.append(project_name)  # first one
                    owned_component.add(project_name)

                m = re.search('^([\\|\s\+\-\\\\]+)([\w\-\.]+):(.+)', line)
                n = re.search('^([\\|\s\+\-\\\\]+)project :([\w\-\.\,\)]+)', line)
                if m or n:
                    if n:
                        level, module = n.group(1, 2)
                        submodules = None
                        owned_component.add(module)
                    elif m:
                        level, module, submodules = m.group(1, 2, 3)
                        submodules = submodules.replace(' (*)', '')

                    level = 1 + (len(level) / 5)

                    while level <= len(hierarchy):
                        hierarchy.pop()

                    if level == len(hierarchy) or level > len(hierarchy):
                        hierarchy.append(module +
                                         ('' if not submodules else (':' + submodules)))

                    # relationship between project_name and module
                    new_relationships = set()
                    new_relationships.add((hierarchy[-2], hierarchy[-1]))

                    #print "DEBUG '%s', '%s', '%s'"%(level, module, submodules)
                    #print "HIERARCHY %s" % hierarchy
                    #print "SET %s" % new_relationships

                    dot_relationship = dot_relationship.union(new_relationships)

                idx += 1
            all_dot_relationships = all_dot_relationships.union(dot_relationship)
            create_dot(gradle_config,
                       '%s/%s.%s.gv' % (OUTPUT_PATH, module_name, gradle_config),
                       dot_relationship,
                       owned_component, options)

        # 1) entire graph
        create_dot(gradle_config,
                   '%s/all-complete.%s.gv' % (OUTPUT_PATH, gradle_config),
                   all_dot_relationships,
                   owned_component,
                   options)
        # 2) overview of owned components only
        _all_dot_relationships = set([t for t in all_dot_relationships
                                      if (t[0] in owned_component
                                          and t[1] in owned_component)])
        create_dot(gradle_config,
                   '%s/all-overview.%s.gv' % (OUTPUT_PATH, gradle_config),
                   _all_dot_relationships,
                   owned_component,
                   options)
        # 3) overview plus one more link
        _all_dot_relationships = set([
            t for t in all_dot_relationships
            if (t[0] in owned_component
                 and not re.search(NODE_DEPRECATED_RE, t[0], re.I)
                 and not re.search('slf4j', t[1], re.I))
            ])
        create_dot(gradle_config,
                   '%s/all-extended.%s.gv' % (OUTPUT_PATH, gradle_config),
                   _all_dot_relationships,
                   owned_component,
                   options)

    for gradle_config, module_path_outputs in gradleconfig2modulepath_outputs.iteritems():
        _generate_dot_files(gradle_config, module_path_outputs)


def load_gradle_dependencies():
    output = {}
    for fname in os.listdir(CACHE_FILE):
        with open("%s/%s" % (CACHE_FILE, fname)) as fd:
            output[fname] = json.loads(fd.read())
    return output


def get_gradle_dependencies(module_path_list):
    outputs = {}
    threads = []
    lock = threading.Lock()

    GRADLE_CONFIGS = ("compile", "runtime", "testRuntime")
    for gradle_config in GRADLE_CONFIGS:
        outputs[gradle_config] = []
        module_path_list_copy = copy.deepcopy(module_path_list)

        # call Gradle command in parallel
        for i in range(0, int(multiprocessing.cpu_count() * 1.25)):
            thread = GradleThread(len(threads),
                                  gradle_config,
                                  module_path_list_copy,
                                  outputs[gradle_config],
                                  lock)
            thread.start()
            threads.append(thread)

        for t in threads:
            t.join()
        threads = []

    for gradle_config in GRADLE_CONFIGS:
        with open("%s/%s" % (CACHE_FILE, gradle_config), 'w') as wd:
            wd.write(json.dumps(outputs[gradle_config]))

    return outputs


if __name__ == '__main__':
    if not os.path.exists('settings.gradle'):
        raise RuntimeError('Unable to find settings.gradle')

    (options, args) = PARSER.parse_args()
    NODE_DEPRECATED_RE = options.deprecated_node_re

    if options.run_gradle:
        try:
            os.remove(CACHE_FILE)
        except OSError, e:
            #print e
            pass
        try:
            shutil.rmtree(CACHE_FILE)
        except OSError, e:
            #print e
            pass
        os.mkdir(CACHE_FILE)

        MODULE_PATHS = []
        with open('settings.gradle') as fd:
            for line in fd:
                m = re.search('^\s*project\([\'"]:'
                              '([\w\-\.\/]+).+[\'"]([\w\-\.]+)', line)
                if not m:
                    continue
                MODULE_PATHS.append(m.group(2, 1))  # name, path
        generate_dot_files(get_gradle_dependencies(MODULE_PATHS), options)
    else:
        generate_dot_files(load_gradle_dependencies(), options)
