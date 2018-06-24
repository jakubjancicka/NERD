#!/bin/sh
mongo nerd --quiet --eval 'db.ip.drop(); db.bgppref.drop(); db.asn.drop(); db.ipblock.drop(); db.org.drop()'
psql -c 'delete from events; delete from events_sources; delete from events_targets;' nerd nerd