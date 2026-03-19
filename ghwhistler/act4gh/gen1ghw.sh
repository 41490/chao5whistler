#!/bin/bash
#########################################
# @Description: 定期生成一段 ghWhistler 视频
# @Author: Chaos42DAMA
# @E-mail: zoomquiet+chaos42dama@gmail.com
# @Github: ZoomQuiet
#   USAGE:
#   crontab -e
#   */1 *    * * *   /opt/code/ghwhistler/act4gh/gen1ghw.sh >> /opt/logs/etc_ontab.log 2>&1
#   tail -f /opt/logs/crontab5m1gen.log

NAME="gen1ghw"
VER="v231116.1742.1"
#########################################
#conda activate rapids WRONG
CONDA_ACTIVATE="/opt/sbin/miniconda3/bin/activate"
CONDA_ENV_NAME="py310"
PY_SRC_ROOT="/opt/code/ghwhistler/act4gh"
LOGF="/opt/logs/crontab5m1gen.log"
#########################################
echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"  >> $LOGF
echo "###::$NAME $VER crontab TASKS"  >> $LOGF
echo "##::run@" `date +"%Y/%m/%d %H:%M:%S"` >> $LOGF
echo "#"  >> $LOGF

source $CONDA_ACTIVATE $CONDA_ENV_NAME #correct
#python Documents/my_python_file_name.py WRONG SEPARATLY GO TO FOLER WHTAN EXECUTE EITH python
cd $PY_SRC_ROOT
#pip list >> $LOGF 2>&1
#python grasp4ghevents2csv.py  >> $LOGF 2>&1
#inv ver >> $LOGF 2>&1
#inv gen1cron --debug=0 >> $LOGF 2>&1
inv gen1cron --debug=0 --vp=/opt/vlog/ghw3 --sp=3000 >> $LOGF 2>&1

conda deactivate
#echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"  >> $LOGF
echo "#"  >> $LOGF
echo "##::$NAME $VER crontab TASKS"  >> $LOGF
echo "###::done@" `date +"%Y/%m/%d %H:%M:%S"` >> $LOGF
echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"  >> $LOGF
