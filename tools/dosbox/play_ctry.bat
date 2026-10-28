@echo off
rem Run from the repository root: the configs mount corpus\ and build\ relative to it.
pushd "%~dp0..\.."
mise x -- dosbox-x -conf tools\dosbox\dosbox-playone.conf
popd
