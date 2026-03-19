#!/bin/bash
#########################################
# @Description: 定期查询 gh-events 
# @Author: Chaos42DAMA
# @E-mail: zoomquiet+chaos42dama@gmail.com
# @Github: ZoomQuiet
#   USAGE:
#   crontab -e
#   */1 * * * *   /opt/code/ghwhistler/crontab/ghe1m2json.sh >> /opt/logs/etc_ontab.log 2>&1

NAME="ghe1m2json"
VER="v231116.1142.1"
#########################################
#conda activate rapids WRONG
CONDA_ACTIVATE="/opt/sbin/miniconda3/bin/activate"
CONDA_ENV_NAME="py310"
PY_SRC_ROOT="/opt/code/ghwhistler/crontab"
LOGF="/opt/logs/crontab1d4rm4json.log"
#########################################
echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"  >> $LOGF
echo "###::$NAME $VER crontab TASKS"  >> $LOGF
echo "##::run@" `date +"%Y/%m/%d %H:%M:%S"` >> $LOGF
echo "#"  >> $LOGF

source $CONDA_ACTIVATE $CONDA_ENV_NAME #correct
#python Documents/my_python_file_name.py WRONG SEPARATLY GO TO FOLER WHTAN EXECUTE EITH python
cd $PY_SRC_ROOT
#pip list >> $LOGF 2>&1
inv del4json            >> $LOGF 2>&1

conda deactivate

#echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"  >> $LOGF
echo "#"  >> $LOGF
echo "##::$NAME $VER crontab TASKS"  >> $LOGF
echo "###::done@" `date +"%Y/%m/%d %H:%M:%S"` >> $LOGF
echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"  >> $LOGF
