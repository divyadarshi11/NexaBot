from setuptools import find_packages, setup

setup(
    name="ai-chatbot-cli",
    version="1.0.0",
    description="A chatbot powered by the Anthropic API, with a terminal and a web front end",
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,
    package_data={"chatbot": ["templates/*.html", "static/*"]},
    install_requires=[
        "anthropic>=0.40.0",
        "python-dotenv>=1.0.0",
        "rich>=13.7.0",
        "flask>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "chatbot=chatbot.cli:main",
            "chatbot-web=chatbot.web:main",
        ],
    },
    python_requires=">=3.9",
)
