from setuptools import setup, find_packages

def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="manasbot",
    version="2.0.0",
    description="Production-ready multi-tenant AI chatbot SaaS platform",
    author="Rahul Kumar",
    packages=find_packages(),
    install_requires=read_requirements(),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "run-chatbot=run_server:main",
        ]
    },
)
