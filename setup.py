from setuptools import find_packages, setup

setup(
    name="inventree-assembly-risk",
    version="0.3.0",
    description="Assembly risk visibility for InvenTree build orders",
    author="Per Vices Corporation",
    packages=find_packages(),
    include_package_data=True,
    package_data={"inventree_assembly_risk": ["static/*.js"]},
    python_requires=">=3.10",
    entry_points={
        "inventree_plugins": [
            "AssemblyRiskPlugin = inventree_assembly_risk.plugin:AssemblyRiskPlugin",
        ]
    },
)
