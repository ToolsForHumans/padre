=======
Scripts
=======

Setup a new host
----------------

The ``setup_new_host.sh`` script should be used when building out a new bot
VM or when building out a new ara (webserver) hosting VM and it sets up the
needed docker and tooling so that ansible + jenkins can connect in and do
things.

Setup a new db host
-------------------

The ``setup_new_db_host.sh`` script should be used when building out a new
*ara* database VM and it sets up mysql and the mysql user and password and
permissions so that later bot and ara instances can connect in and do read
or write things.

Bot starting
------------

The ``start.sh`` script is used as the main bot container entrypoint (it
can also be used by developers to start a development bot); it is primary
used for the dockerfile we have.
