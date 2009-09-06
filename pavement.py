from setuptools import find_packages
import glob

from paver.easy import *
from paver.setuputils import find_package_data
from paver import setuputils
try:
    import paver.virtual
except ImportError:
    # There's no virtual module in paver-minilib.zip used during the bootstrap
    # installation.
    pass

setuputils.install_distutils_tasks()

install_requires = [
    'nose',
    'WebOb',
    'Paste',
    # Python Imaging Library should be installed from the .exe
    # on Windows.
    #'PIL',
    # ... same story for Python Win32.
    #'python-win32',
]
try:
    import json
except ImportError:
    # Python < 2.6
    install_requires.append("simplejson")

if sys.platform == "darwin":
    install_requires.append('appscript')

options(
    setup=Bunch(
        name="W3TestRunner",
        version="0.1",
        packages=find_packages(),
        zip_safe=False,
        entry_points={
            'console_scripts': [
                'testrunner = w3testrunner.runner:main',
            ]
        },
        install_requires = install_requires,
        package_data=find_package_data('w3testrunner', 'w3testrunner',
                                       only_in_packages=False),
        author="Sylvain Pasche",
        author_email="sylvain.pasche@gmail.com",
        license="BSD",
        keywords="browser testing",
        url="http://www.browsertests.org/",
    ),
    virtualenv=Bunch(
        packages_to_install=["."],
    ),
)

@task
@needs(['paver.virtual.bootstrap'])
def bootstrap():
    """Monkeypatches bootstrap.py to add a Windows manifest for easy_install
       That manifest should prevent easy_install executation failure caused
       by an elevation attempt."""
    lines = open("bootstrap.py").readlines()
    try:
        after_install_line = lines.index("""def after_install(options, home_dir):\n""")
        insert_after_line = lines.index(
            """        bin_dir = join(home_dir, 'Scripts')\n""",
            after_install_line)
        lines.insert(insert_after_line + 1,
            """        shutil.copy('easy_install.exe.manifest', 'Scripts')\n""")
    except ValueError:
        print "Didn't find the line where to instert bootstrap.py modification"
    open("bootstrap.py", "w").writelines(lines)

@task
@needs(['generate_setup', 'minilib', 'bootstrap', 'setuptools.command.sdist'])
def sdist():
    """Overrides sdist to generate everything needed."""
    pass

# adapted from git://github.com/teepark/actionscript-bundler.git/
@task
@needs(['setuptools.command.clean'])
def clean():
    for p in map(path, ('W3TestRunner.egg-info', 'setup.py', 'bootstrap.py',
                        'paver-minilib.zip', 'build', 'dist',
                        'w3testrunner/reftest_results')):
        if p.exists():
            if p.isdir():
                p.rmtree()
            else:
                p.remove()
