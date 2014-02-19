python-lbaasclient
============

Recommended installation instructions:

```
mkdir python-lbaasclient
cd python-lbaasclient
git checkout https://github.com/lbrackspace/python-lbaasclient.git lbaasclient
virtualenv .venv
. .venv/bin/activate
pip install -r lbaasclient/requirements.txt
cp lbaasclient/contrib/lbaas .
```

Use the same export values as Nova for configuration (OS_USERNAME, OS_TENANT_ID, etc).

```
./lbaas list
```
