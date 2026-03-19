#inv gen2fcs --mov="/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv" --aimp="../log/f4v/fcs_bg_1.png" --subt="Scavengers.Reign.S01E01" --debug=0
#inv fcolor2v --mov="/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv" --subt="Scavengers.Reign.S01E01" --aimp="../log/f4v/fcs_bg_1.png" --aimv="../log/f4v/fcs_bg_1.mp4"  --debug=0

BASEP="/opt/vlog/2021冥想指南HeadspaceGuide-to-Meditation"
AIMP="../log/f4v"
AIMF="fcs4hg2m_"

SRCV="Headspace.Guide.to.Meditation.S01E01.How.to.Get.Started.1080p.mp4"
SUBT="Headspace.Guide.to.Meditation.S01E01"
FNO=1
#inv fcolor2v --mov="$BASEP/$SRCV" --subt="$SUBT" --aimp="$AIMP/$AIMF-$FNO.png" --aimv="$AIMP/$AIMF-$FNO.mp4" --au2v="$AIMP/$AIMF-$FNO-bgau.mp4" --debug=0

BASEP="/opt/vlog/2019S1FAMankind"
AIMP="../log/ghw3"
AIMF="bg4allmankind"
#FNO=1
for FNO in {01..10}; do
    SRCV="4AM-S01E$FNO.mp4"
    SUBT="2019/For All Mankind/S1E$FNO"
   #convert image_$i.jpg image_$i.png
   echo
   echo "<- $BASEP/$SRCV"
   echo " -> $SUBT"
   echo " --> $AIMP/$AIMF-$FNO.png"
   inv img4mfc --mov="$BASEP/$SRCV" --subt="$SUBT" --aimp="$AIMP/$AIMF-$FNO.png" --debug=0
done


