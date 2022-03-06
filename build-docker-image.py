#!/usr/bin/env python3
import os
import subprocess
from textwrap import dedent

def get_input(input_name, default=None):
    """
    Return value of given input variable.

    Returns None if input variable is not present
    """
    return os.environ.get(f'INPUT_{input_name}', default)

def docker_login(registry, username, password):
    """
    Login to a docker registry with given username & password
    """
    subprocess.run([
        'docker', 'login', registry,
        '-u', username,
        '--password-stdin'
    ], input=password, check=True)

def docker_pull(image_name):
    """
    Pull a docker image if present.
    """
    # Don't error if command fails
    subprocess.run([
        'docker', 'pull', image_name
    ], check=False)


def run_r2d(nb_user, repo_dir, image_name, cache_from, appendix, src_dir):
    """
    Run repo2docker
    """
    cmd = [
        'jupyter-repo2docker',
        '--no-run',
        '--user-id', '1000',
        '--user-name', nb_user,
        '--target-repo-dir', repo_dir,
        '--image-name', image_name,
        '--cache-from', cache_from,
    ]

    if appendix:
        cmd += ['--appendix', appendix]

    cmd.append(src_dir)
    subprocess.run(cmd, check=True)


def run_image_tests(repo_dir, full_image_name):
    """
    Run image tests found in image-tests/
    """
    tests_script = dedent("""
        export PYTEST_FLAGS="";

        # If there is a requirements.txt file inside image-tests, install it.
        # Useful if you want to install a bunch of pytest packages.
        [ -f image-tests/requirements.txt ] && \
            echo "Installing from image-tests/requirements.txt..." && \
            python3 -m pip install --no-cache -r image-tests/requirements.txt;

        # If pytest is not already installed in the image, install it.
        which py.test > /dev/null || \
            echo "Installing pytest inside the image..." && \
            python3 -m pip install --no-cache pytest > /dev/null;

        # If there are any .ipynb files in image-tests, install pytest-notebook
        # if necessary, and set PYTEST_FLAGS so notebook tests are run.
        ls image-tests/*.ipynb > /dev/null && \
            echo "Found notebooks, using pytest-notebook to run them..." && \
            export PYTEST_FLAGS="--nb-test-files ${PYTEST_FLAGS}" && \
            python3 -c "import pytest_notebook" 2> /dev/null || \
                python3 -m pip install --no-cache pytest-notebook > /dev/null;

        py.test ${PYTEST_FLAGS} image-tests/
    """)

    subprocess.run([
        'docker', 'run', '-u', '1000',
        '-w', repo_dir, full_image_name,
        '/bin/bash', '-c', tests_script
    ], check=True)

def main():
    # Parse inputs

    # Appendix is arbitrary Dockerfile syntax that is run by repo2docker
    # at the end of the build process. Users can specify the naem of a file
    # that contains the appendix, and if they do, we read it to pass it on to repo2docker
    # later
    if get_input('APPENDIX_FILE'):
        with open(get_input('APPENDIX_FILE')) as f:
            appendix = f.read()
    else:
        appendix = None

    repo_name = os.environ['GITHUB_REPOSITORY'].split('/')[-1]

    # determine name of the image to be built
    if get_input('IMAGE_NAME'):
        image_name = get_input('IMAGE_NAME')
    else:
        if get_input('DOCKER_USERNAME') is None:
            image_name = f'{os.environ["GITHUB_ACTOR"]}/{repo_name}'
        else:
            image_name = f'{get_input("DOCKER_USERNAME")}/{repo_name}'

    if get_input('DOCKER_REGISTRY'):
        image_name = f'{get_input("DOCKER_REGISTRY")}/{image_name}'

    image_name = image_name.lower()

    # If notebook user is not specified, or we are using mybinder (where we can't set the username),
    # default to jovyan
    if not get_input('NOTEBOOK_USER') or get_input('MYBINDERORG_TAG') or get_input('BINDER_CACHE'):
        notebook_user = 'jovyan'
    else:
        notebook_user = get_input('NOTEBOOK_USER')

    repo_dir = get_input('REPO_DIR', f'/home/{notebook_user}')

    sha = os.environ['GITHUB_SHA'][:12]
    full_image_name = f'{image_name}:{sha}'

    push = not get_input('NO_PUSH')

    src_dir = os.getcwd()

    # Login to registry if needed
    if push and get_input('DOCKER_PASSWORD') and get_input('DOCKER_USERNAME'):
        docker_login(get_input('DOCKER_REGISTRY'), get_input('DOCKER_USERNAME'), get_input('DOCKER_PASSWORD'))

    docker_pull(full_image_name)

    print(f"::group::Build {full_image_name}")
    run_r2d(notebook_user, repo_dir, full_image_name, image_name, appendix, src_dir)
    print("::endgroup::")

    if os.path.isdir(f'{src_dir}/image-tests'):
        print("::group::Running image tests from image-tests/")
        run_image_tests(repo_dir, full_image_name)
        print("::endgroup::")

    if push:
        # Push manually, not with repo2docker so we can run tests before pushing
        print("::group::Pushing images")
        subprocess.run([
            'docker', 'push', full_image_name
        ], check=True)

        # Additional tags to build and push
        additional_tags = []
        if not get_input('LATEST_TAG_OFF'):
            additional_tags.append('latest')

        if get_input('ADDITIONAL_TAG'):
            additional_tags.append(get_input('ADDITIONAL_TAG'))

        for at in additional_tags:
            subprocess.run([
                'docker', 'tag', full_image_name, f'{image_name}:{at}'
            ], check=True)
            subprocess.run([
                'docker', 'push', f'{image_name}:{at}'
            ])
        print("::endgroup::")


if __name__ == '__main__':
    main()