#!/usr/bin/env python
"""
Fetch Package details from Contrail Docker Containers for OSS purpose
Collected details would be saved as a pipe seperated file
"""

# OSS Package Retriever
# Authored-By: Nagendra Maynattamai <npchandran@juniper.net>

# Version
VERSION = '1.0'

import sys
import argparse
import json
import os
import logging
import re
import shutil
import subprocess
import tempfile
import time


# Globals
timestamp = time.strftime('%m%d%y%H%M%S')
DEFAULTS = {
    'docker_registry': "svl-artifactory.juniper.net/contrail-nightly",
    'contrail_version': "1912-latest",
    'csv_path': 'oss-package-dump-%s.csv' % timestamp,
    'log_level': logging.INFO,
    'log_file': '/tmp/oss-package-retriever-%s.log' % timestamp
}

logger = logging.getLogger("OSS-PACKAGE-RETRIEVER")
COLUMNS = [
    'Containers',
    'Package Repo',
    'Source Package Name',
    'Component Name (binary pkg name)',
    'Binary Package Version',
    'Binary Package Release',
    'OSS License',
    'Description',
    'Is the Component Modified by Juniper (Yes/No)',
    ('How Integrated with Juniper code: specify all applicable: '
     '1) Statically linked '
     '2) Dynamically Linked '
     '3) Remote Procedure calls '
     '4) Loadable kernel modules '
     '5) Merely bundled/stand-alone '
     '6) Dynamically loaded (e.g. Java/Python/PAM modules/Apache mod_*)'),
    'Does this component use encryption technologies (yes/No)',
    'URL for Licensor or OSS project (Upstream Source URL)',
    'OSC questions',
    'Final Response to OSC']

def parse_args(args):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(**DEFAULTS)
    parser.add_argument('--version', '-v',
                        action='version',
                        version=VERSION,
                        help='Print version and exit')
    parser.add_argument('--dont-rm-images', action='store_true',
                        help='Leave downloaded images in the host')
    parser.add_argument('--dont-add-registry-to-host', action='store_true',
                        help='Add given registry to this host and restart docker')
    parser.add_argument('--docker-registry', action='store',
                        help='Docker registry name, eg: svl-artifactory.juniper.net/contrail-nightly')
    parser.add_argument('--contrail-version', action='store',
                        help='Contrail Build version, eg: 1912-latest')
    parser.add_argument('--csv-path', action='store',
                        help='Absolute path of the output csv file eg: /tmp/out.csv')
    parsed_args = parser.parse_args(args)

    # update logger
    formatter = logging.Formatter('[%(asctime)s - %(funcName)s - %(levelname)s]: %(message)s')
    logger.setLevel(level=logging.DEBUG)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level=parsed_args.log_level)
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(parsed_args.log_file)
    file_handler.setLevel(level=logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    # print working config set
    logger.info('Working with Config Set: ')
    for arg_k, arg_v in parsed_args._get_kwargs():
        logger.info('%s:  %s' % (arg_k, arg_v))
    
    return parsed_args

def run_cmd(cmd):
    ok = True
    out = ()
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout_value, stderr_value = proc.communicate()
        if 'not found' in repr(stderr_value):
            ok = False
            logger.debug('Command: (%s)' % cmd)
            logger.debug('STDOUT: %s' % stdout_value)
            logger.debug('STDERR: %s' % stderr_value)
            out = (stdout_value.strip(), 'NotFound') 
        elif 'no such file or directory' in repr(stderr_value):
            ok = False
            logger.debug('Command: (%s)' % cmd)
            logger.debug('STDOUT: %s' % stdout_value)
            logger.debug('STDERR: %s' % stderr_value)
            out = (stdout_value.strip(), 'NoSuchFileOrDirectory')
        else:
            out = (stdout_value.strip(), stderr_value.strip())
    except subprocess.CalledProcessError:
        ok = False
    return ok, out

# Remove download docker images from host
def remove_docker_images(skip, version):
    if skip:
        return
    cmd = "docker images | grep %s | awk '{print $3}' | xargs docker rmi" % version
    ok, out = run_cmd(cmd)
    if not ok:
        raise Exception('Failed to remove docker images...')

# Add registry to host
def add_registry_to_host(skip, registry):
    if skip:
        return
    registry = registry.split('/')[0]
    docker_json = '/etc/docker/daemon.json'
    mode = 'w+'
    data = {'insecure-registries': []}
    if os.path.isfile(docker_json):
        try:
            with open(docker_json, 'r') as fid:
                data = json.load(fid)
        except ValueError as exc:
            pass
        if ('insecure-registries' in data.keys() and
            registry in data['insecure-registries']):
            logger.info('Registry (%s) exists in the host' % registry)
            return
    logger.info('Registry (%s) do not exists in the host' % registry)
    logger.info('Adding Registry (%s) to the host' % registry)
    data['insecure-registries'].append(registry)
    with open(docker_json, mode) as fid:
        fid.write('%s\n' % json.dumps(data))
        fid.flush()
    ok, out = run_cmd('systemctl restart docker')
    if not ok:
        log.error('Unable to add registry (%s) to host' % registry)
        raise Exception('Restart Docker Service Failed...')

# Retrieve docker names
def fetch_docker_names(docker_registry):
    docker_names = []
    ok, docker_names_out = run_cmd(
        'curl https://%s/ | grep -Po "href=\\"\K[^/]*"' % docker_registry)
    if not ok:
        raise DockerNameFetchFailed(
            'Unable to retrieve docker names from registry (%s)' % docker_registry)
        docker_names = []
    else:
        docker_names = docker_names_out[0].split('\n')
    logger.info('Total Docker Containers found (%d)' % len(docker_names))
    return docker_names

def docker_pull(name, registry, version):
    logger.info('Pulling Docker Container Image of (%s)' % name)
    cmd = 'docker pull %s/%s:%s' % (registry, name, version)
    ok, out = run_cmd(cmd)
    return ok, out

# Download docker images to local machine
def fetch_docker_images(names, registry, version):
    image_not_found = []
    for name in names:
        ok, out = docker_pull(name, registry, version)
        if not ok and out[1] == 'NotFound':
            logger.warn('Docker image of (%s) is not found' % name)
            image_not_found.append(name)
    logger.warn(
        'Total Docker Image not found #%d' % len(image_not_found))
    return image_not_found

def format_docker_run_cmd():
    docker_run_cmd = 'docker run --rm '
    docker_run_cmd += '--privileged --entrypoint="" '
    return docker_run_cmd

def populate_deb_script(docker_container):
    tmp_dir = tempfile.mkdtemp(prefix='oss-test')
    script_path = os.path.join(tmp_dir, 'deb_script.sh')
    script_lines = """#!/usr/bin/env bash
        set -e
        container_name=%s
        all_pkgs=$(apt list --installed | grep -v "apt does not have a stable" | grep -v "Listing..." | awk 'BEGIN { FS = "/" } ; {print $1}')
        set +e
        apt-get update >> /dev/null
        set -e
        for pkg in $all_pkgs; do
            IFS=',' read -ra out <<< $(dpkg-query --show  -f '\"${Source}\",${Package},${Version},"${Homepage}",\"${Description}\"' $pkg)
            license=$(grep -oP '^License: \K.*' /usr/share/doc/$pkg/copyright | tr '\\n' '. ' | sort | uniq)
            pkg_repo=$(apt-cache madison ${out[1]} | grep ${out[2]} | awk 'BEGIN { FS = "|" } ; { print $3 }')
            echo "$container_name|$pkg_repo|${out[0]}|${out[1]}|${out[2]}|RLS-NA|\"${license}\"|${out[3]}||||${out[4]}|||"
        done
    """ % docker_container

    script = re.sub('\n\s+', '\n', script_lines)
    with open(script_path, 'w') as fid:
        fid.write('%s\n' % script)
        fid.flush()
    os.chmod(script_path, 0o755)
    return script_path

def format_deb_cmd(docker_name, docker_registry, contrail_version):
    docker_run_cmd = format_docker_run_cmd()
    script_path = populate_deb_script(docker_name)
    docker_run_cmd += '--name oss-test-%s ' % docker_name
    docker_run_cmd += '-v %s:/tmp/fetch_packages.sh ' % script_path
    docker_run_cmd += '%s/%s:%s ' % (docker_registry, docker_name, contrail_version)
    docker_run_cmd += '/tmp/fetch_packages.sh'
    return docker_run_cmd, script_path
    
def fetch_deb_package_details(docker_names, docker_registry, contrail_version):
    fetch_failed = []
    package_by_name_dict = {}
    for docker_name in docker_names:
        docker_run_cmd, script_path = format_deb_cmd(
            docker_name, docker_registry, contrail_version)
        logger.info('Fetching packages from Docker container (%s)' % docker_name)
        ok, out = run_cmd(docker_run_cmd)
        shutil.rmtree(os.path.dirname(script_path))
        if not ok:
            logger.warn('Deb Fetch packages from Docker container (%s): FAILED' % docker_name)
            fetch_failed.append(docker_name)
            continue
        deb_infos = out[0].split('\n')
        for deb_info in deb_infos:
            deb_split = deb_info.split('|')
            deb_name = "_".join(deb_split[3:5])
            if deb_name in package_by_name_dict:
                package_by_name_dict[deb_name][0] += ' %s' % deb_split[0]
                continue
            package_by_name_dict[deb_name] = deb_split
    return package_by_name_dict, fetch_failed

def format_rpm_cmd(docker_name, docker_registry, contrail_version):
    docker_run_cmd = format_docker_run_cmd()
    docker_run_cmd += '--name oss-test-%s ' % docker_name
    docker_run_cmd += '%s/%s:%s ' % (docker_registry, docker_name, contrail_version)
    docker_run_cmd += (
        'bash -c \'/usr/bin/repoquery --qf "%s|%%{repoid}|%%{sourcerpm}|%%{name}|%%{version}|%%{release}|\"%%{license}\"|\"%%{summary}\"||||\"%%{url}\"||" $(rpm -qa)\'' % (
        docker_name))
    return docker_run_cmd
    
# Execute the script in the docker containers
def fetch_rpm_package_details(docker_names, docker_registry, contrail_version):
    fetch_failed = []
    package_by_name_dict = {}
    for docker_name in docker_names:
        package_fetch_cmd = format_rpm_cmd(
            docker_name, docker_registry, contrail_version)
        logger.info('Fetching packages from Docker container (%s)' % docker_name)
        ok, out = run_cmd(package_fetch_cmd)
        if not ok:
            logger.warn('RPM Fetch packages from Docker container (%s) FAILED' % docker_name)
            fetch_failed.append(docker_name)
            continue
        rpm_infos = out[0].split('\n')
        for rpm_info in rpm_infos:
            rpm_split = rpm_info.split('|')
            rpm_name = "_".join(rpm_split[3:6])
            if rpm_name in package_by_name_dict:
                if package_by_name_dict[rpm_name][1] == rpm_split[1]:
                   package_by_name_dict[rpm_name][0] += ' %s' % rpm_split[0]
                   continue
            package_by_name_dict[rpm_name] = rpm_split
    return package_by_name_dict, fetch_failed

def write_output(csv_path, package_dict):
    if not package_dict:
        return
    with open(csv_path, 'w+') as fid:
        logger.info('Writing package info to (%s)' % csv_path)
        fid.write('%s\n' % "|".join(COLUMNS))
        fid.flush()
        for package_info in package_dict.values():
            fid.write('%s\n' % "|".join(package_info))
            fid.flush()
    
def main():
    cli_args = parse_args(sys.argv[1:])
    add_registry_to_host(
        cli_args.dont_add_registry_to_host, cli_args.docker_registry)
    docker_names = fetch_docker_names(cli_args.docker_registry)
    docker_not_found = fetch_docker_images(
        docker_names, cli_args.docker_registry, cli_args.contrail_version)
    docker_downloaded = list(set(docker_names) - set(docker_not_found))
    package_dict, fetch_failed = fetch_rpm_package_details(
        docker_downloaded, cli_args.docker_registry, cli_args.contrail_version)
    write_output(cli_args.csv_path, package_dict)
    #fetch_failed = ['contrail-external-cassandra', 'contrail-external-redis', 'contrail-external-rabbitmq', 'contrail-external-zookeeper']
    deb_package_dict, fetch_failed = fetch_deb_package_details(
        fetch_failed, cli_args.docker_registry, cli_args.contrail_version)
    write_output('deb_%s' % cli_args.csv_path, deb_package_dict)
    remove_docker_images(
        cli_args.dont_rm_images, cli_args.contrail_version)
    logger.info("Total Found Packages: %s" % len(package_dict))
    if docker_not_found:
       logger.error("Docker Image not found for dockers = (%s)" % " ".join(docker_not_found))
    if fetch_failed:
       logger.error("Package Fetch failed for dockers = (%s)" % " ".join(fetch_failed))
    logger.info("CSV output file is generated at (%s)" % cli_args.csv_path)

# ** MAIN **
if __name__ == '__main__':
    main()
