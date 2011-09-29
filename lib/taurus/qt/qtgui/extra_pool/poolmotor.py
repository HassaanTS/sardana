#!/usr/bin/env python

#############################################################################
##
## This file is part of Taurus, a Tango User Interface Library
## 
## http://www.tango-controls.org/static/taurus/latest/doc/html/index.html
##
## Copyright 2011 CELLS / ALBA Synchrotron, Bellaterra, Spain
## 
## Taurus is free software: you can redistribute it and/or modify
## it under the terms of the GNU Lesser General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
## 
## Taurus is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
## 
## You should have received a copy of the GNU Lesser General Public License
## along with Taurus.  If not, see <http://www.gnu.org/licenses/>.
##
#############################################################################

import sys
import copy
import PyTango
import numpy

from taurus.qt import Qt

import taurus
import taurus.qt.qtcore.mimetypes
from taurus.qt.qtgui.dialog import ProtectTaurusMessageBox
from taurus.qt.qtgui.base import TaurusBaseWidget
from taurus.qt.qtgui.container import TaurusWidget
from taurus.qt.qtgui.display import TaurusLabel
from taurus.qt.qtgui.input import TaurusValueLineEdit
from taurus.qt.qtgui.input import TaurusValueSpinBox
from taurus.qt.qtgui.panel import DefaultLabelWidget
from taurus.qt.qtgui.panel import DefaultUnitsWidget
from taurus.qt.qtgui.panel import TaurusValue, TaurusAttrForm
from ui_poolmotorslim import Ui_PoolMotorSlim


class LimitsListener(Qt.QObject):
    """
    A class that listens to changes on motor limits.
    If that is the case it emits a signal so the application
    can do whatever with it.
    """
    def __init__(self):
        Qt.QObject.__init__(self)

    def eventReceived(self, evt_src, evt_type, evt_value):
        if evt_type not in [taurus.core.TaurusEventType.Change, taurus.core.TaurusEventType.Periodic]:
            return
        limits = evt_value.value
        self.emit(Qt.SIGNAL('updateLimits(PyQt_PyObject)'), limits.tolist())

class PoolMotorClient():

    maxint_in_32_bits = 2147483647
    def __init__(self):
        self.motor_dev = None
        self.has_limits = False
        self.has_encoder = False

    def setMotor(self, pool_motor_dev_name):
        # AT SOME POINT THIS WILL BE USING THE 'POOL' TAURUS EXTENSION
        # TO OPERATE THE MOTOR INSTEAD OF A 'TANGO' TAURUSDEVICE
        try:
            self.motor_dev = taurus.Device(pool_motor_dev_name)
            # IT IS IMPORTANT TO KNOW IF IT IS AN ICEPAP MOTOR, SO EXTRA FEATURES CAN BE PROVIDED
            # PENDING.
            self.has_limits = hasattr(self.motor_dev, 'Limit_Switches')
            self.has_encoder = hasattr(self.motor_dev, 'Encoder')
        except Exception,e:
            print 'EXCEPTION CREATING MOTOR DEVICE...\n'+str(e)

    def moveMotor(self, pos):
        #self.motor_dev['position'] = pos
        # Make use of Taurus operations (being logged)
        self.motor_dev.getAttribute('Position').write(pos)

    def moveInc(self, inc):
        self.moveMotor(self.motor_dev['position'].value + inc)

    def jogNeg(self):
        neg_limit = - ( (self.maxint_in_32_bits / 2) - 1)
        # THERE IS A BUG IN THE ICEPAP THAT DOES NOT ALLOW MOVE ABSOLUTE FURTHER THAN 32 BIT
        # SO IF THERE ARE STEPS PER UNIT, max_int HAS TO BE REDUCED
        if hasattr(self.motor_dev, 'step_per_unit'):
            neg_limit = neg_limit / self.motor_dev['step_per_unit'].value
        try:
            min_value = self.motor_dev.getAttribute('Position').getConfig().getValueObj().min_value
            neg_limit = float(min_value)
        except Exception,e:
            pass
        self.moveMotor(neg_limit)

    def jogPos(self):
        pos_limit = (self.maxint_in_32_bits / 2) - 1
        # THERE IS A BUG IN THE ICEPAP THAT DOES NOT ALLOW MOVE ABSOLUTE FURTHER THAN 32 BIT
        # SO IF THERE ARE STEPS PER UNIT, max_int HAS TO BE REDUCED
        if hasattr(self.motor_dev, 'step_per_unit'):
            pos_limit = pos_limit / self.motor_dev['step_per_unit'].value
        try:
            max_value = self.motor_dev.getAttribute('Position').getConfig().getValueObj().max_value
            pos_limit = float(max_value)
        except Exception,e:
            pass
        self.moveMotor(pos_limit)

    def goHome(self):
        pass

    def abort(self):
        self.motor_dev.abort()

class LabelWidgetDragsDeviceAndAttribute(DefaultLabelWidget):
    """ Offer richer mime data with taurus-device, taurus-attribute, and plain-text. """
    def mouseMoveEvent(self, event):
        model = self.taurusValueBuddy().getModelName()
        mimeData = Qt.QMimeData()
        mimeData.setText(self.text())
        attr_name = model
        dev_name = model.rpartition('/')[0]
        mimeData.setData(taurus.qt.qtcore.mimetypes.TAURUS_DEV_MIME_TYPE, dev_name)
        mimeData.setData(taurus.qt.qtcore.mimetypes.TAURUS_ATTR_MIME_TYPE, attr_name)

        drag = Qt.QDrag(self)
        drag.setMimeData(mimeData)
        drag.setHotSpot(event.pos() - self.rect().topLeft())
        dropAction = drag.start(Qt.Qt.CopyAction)

class PoolMotorConfigurationForm(TaurusAttrForm):

    def __init__(self, parent=None, designMode=False):
        TaurusAttrForm.__init__(self, parent, designMode)
        self._form.setWithButtons(False)

    def getMotorControllerType(self):
        modelObj = self.getModelObj()
        modelNormalName = modelObj.getNormalName()
        poolDsId = modelObj.getHWObj().info().server_id
        db = taurus.Database()
        pool_devices = tuple(db.get_device_class_list(poolDsId).value_string)
        pool_dev_name = pool_devices[pool_devices.index('Pool') - 1]
        pool = taurus.Device(pool_dev_name)
        poolMotorInfos = pool["MotorList"].value
        for motorInfo in poolMotorInfos:
            # BE CAREFUL, THIS ONLY WORKS IF NOBODY CHANGES THE DEVICE NAME OF A MOTOR!!!
            # ALSO THERE COULD BE A CASE PROBLEM, BETTER DO COMPARISONS WITH .lower()
            #to better understand following actions
            #this is an example of one motor info record
            #'dummymotor10 (motor/dummymotorctrl/10) (dummymotorctrl/10) Motor',
            motorInfos = motorInfo.split()
            if modelNormalName.lower() == motorInfos[1][1:-1].lower():
                controllerName = motorInfos[2][1:-1].split("/")[0]

        poolControllerInfos = pool["ControllerList"].value
        for controllerInfo in poolControllerInfos:
            #to better understand following actions
            #this is an example of one controller info record
            #'dummymotorctrl (DummyMotorController.DummyMotorController/dummymotorctrl) - Motor Python ctrl (DummyMotorController.py)'
            controllerInfos = controllerInfo.split()
            if controllerName.lower() == controllerInfos[0].lower():
                controllerType = controllerInfos[1][1:-1].split("/")[0]
        return controllerType

    def getDisplayAttributes(self, controllerType):
        attributes = ['position',
                      'state', 
                      'status', 
                      'velocity', 
                      'acceleration', 
                      'base_rate', 
                      'step_per_unit',
                      'dialposition',
                      'sign', 
                      'offset',  
                      'backlash'] 

        if controllerType == "IcePAPCtrl.IcepapController":
            attributes.insert(1,"encoder")
            attributes.extend(['frequency', 
                               'poweron', 
                               'closedloop', 
                               'useencodersource', 
                               'encodersource', 
                               'encodersourceformula', 
                               'statusstopcode', 
                               'statusdisable', 
                               'statusready', 
                               'statuslim-', 
                               'statuslim+', 
                               'statushome'])

        elif controllerType == "PmacCtrl.PmacController":
            attributes.extend(["motoractivated", 
                               "negativeendlimitset", 
                               "positiveendlimitset", 
                               "handwheelenabled",
                               "phasedmotor", 
                               "openloopmode", 
                               "runningdefine-timemove", 
                               "integrationmode",
                               "dwellinprogress", 
                               "datablockerror", 
                               "desiredvelocityzero", 
                               "abortdeceleration", 
                               "blockrequest", 
                               "homesearchinprogress", 
                               "assignedtocoordinatesystem",
                               "coordinatesystem", 
                               "amplifierenabled",
                               "stoppedonpositionlimit", 
                               "homecomplete", 
                               "phasingsearcherror", 
                               "triggermove",
                               "integratedfatalfollowingerror", 
                               "i2t_amplifierfaulterror", 
                               "backlashdirectionflag",
                               "amplifierfaulterror", 
                               "fatalfollowingerror", 
                               "warningfollowingerror", 
                               "inposition",
                               "motionprogramrunning"])

        elif controllerType == "TurboPmacCtrl.TurboPmacController":
            attributes.extend(["motoractivated", 
                               "negativeendlimitset", 
                               "positiveendlimitset", 
			       "extendedservoalgorithmenabled"
                               "amplifierenabled",
                               "openloopmode", 
                               "movetimeractive", 
                               "integrationmode",
                               "dwellinprogress", 
                               "datablockerror", 
                               "desiredvelocityzero", 
                               "abortdeceleration", 
                               "blockrequest", 
                               "homesearchinprogress", 
                               "user-writtenphaseenable",
                               "user-writtenservoenable", 
                               "alternatesource/destination",
                               "phasedmotor",
                               "followingoffsetmode",
                               "followingenabled",
                               "errortriger",
                               "softwarepositioncapture",
                               "integratorinvelocityloop",
                               "alternatecommand-outputmode",
                               "coordinatesystem",
                               "coordinatedefinition",
                               "assignedtocoordinatesystem",
                               "foregroundinposition",
                               "stoppedondesiredpositionlimit",
                               "stoppedonpositionlimit", 
                               "homecomplete", 
                               "phasing_search/read_active", 
                               "triggermove",
                               "integratedfatalfollowingerror", 
                               "i2t_amplifierfaulterror", 
                               "backlashdirectionflag",
                               "amplifierfaulterror", 
                               "fatalfollowingerror", 
                               "warningfollowingerror", 
                               "inposition"])            
        return attributes

    def setModel(self, modelName):
        TaurusAttrForm.setModel(self, modelName)
        controllerType = self.getMotorControllerType()
        attributes = self.getDisplayAttributes(controllerType)
        #self.setViewFilters([lambda a: a.name.lower() in attributes])
        self.setSortKey(lambda att: attributes.index(att.name.lower()) if att.name.lower() in attributes else 1)

class PoolMotorSlim(TaurusWidget, PoolMotorClient):

    __pyqtSignals__ = ("modelChanged(const QString &)",)

    def __init__(self, parent = None, designMode = False):
        TaurusWidget.__init__(self, parent)

        #self.call__init__wo_kw(Qt.QWidget, parent)
        #self.call__init__(TaurusBaseWidget, str(self.objectName()), designMode=designMode)
        PoolMotorClient.__init__(self)
        self.show_context_menu = True

        self.setAcceptDrops(True)

        self.ui = Ui_PoolMotorSlim()
        self.ui.setupUi(self)

        # CREATE THE TaurusValue that can not be configured in the Designer
        self.taurus_value = TaurusValue(self.ui.taurusValueContainer)

        # Use a DragDevAndAttributeLabelWidget to provide a richer QMimeData content
        self.taurus_value.setLabelWidgetClass(LabelWidgetDragsDeviceAndAttribute)

        # Make the label to be the device alias
        self.taurus_value.setLabelConfig('dev_alias')

        self.taurus_value_enc = TaurusValue(self.ui.taurusValueContainer)

        # THIS WILL BE DONE IN THE DESIGNER
        # Config Button will launch a PoolMotorConfigurationForm
#        19.08.2011 after discussion between cpascual, gcui and zreszela, Configuration Panel was rolled back to 
#        standard TaurusAttrForm - list of all attributes alphabetically ordered 
#        taurus_attr_form = PoolMotorConfigurationForm()        
        taurus_attr_form = TaurusAttrForm()

        taurus_attr_form.setMinimumSize(Qt.QSize(470,800))
        self.ui.btnCfg.setWidget(taurus_attr_form)
        self.ui.btnCfg.setUseParentModel(True)

        # ADD AN EVENT FILTER FOR THE STATUS LABEL IN ORDER TO PROVIDE JUST THE STRING FROM THE CONTROLLER (LAST LINE)
        def just_ctrl_status_line(evt_src, evt_type, evt_value):
            if evt_type not in [taurus.core.TaurusEventType.Change, taurus.core.TaurusEventType.Periodic]:
                return evt_src, evt_type, evt_value
            try:
                status = evt_value.value
                last_line = status.split('\n')[-1]
                new_evt_value = PyTango.DeviceAttribute(evt_value)
                new_evt_value.value = last_line
                return evt_src, evt_type, new_evt_value
            except:
                return evt_src, evt_type, evt_value
        self.ui.lblStatus.insertEventFilter(just_ctrl_status_line)

        # These buttons are just for showing if the limit is active or not
        self.ui.btnMin.setEnabled(False)
        self.ui.btnMax.setEnabled(False)

        # HOMING NOT IMPLMENTED YET
        self.ui.btnHome.setEnabled(False)

        # DEFAULT VISIBLE COMPONENTS
        self.toggleHideAll()
        self.toggleMoveAbsolute(True)
        self.toggleStopMove(True)

        #################################################################################################################
        ################
        # SET TAURUS ICONS 
        ################
        self.ui.btnMin.setText('')
        self.ui.btnMin.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/list-remove.svg'))
        self.ui.btnMax.setText('')
        self.ui.btnMax.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/list-add.svg'))

        self.ui.btnGoToNeg.setText('')
        self.ui.btnGoToNeg.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_skip_backward.svg'))
        self.ui.btnGoToNegPress.setText('')
        self.ui.btnGoToNegPress.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_seek_backward.svg'))
        self.ui.btnGoToNegInc.setText('')
        self.ui.btnGoToNegInc.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_backward.svg'))
        self.ui.btnGoToPos.setText('')
        self.ui.btnGoToPos.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_skip_forward.svg'))
        self.ui.btnGoToPosPress.setText('')
        self.ui.btnGoToPosPress.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_seek_forward.svg'))
        self.ui.btnGoToPosInc.setText('')
        self.ui.btnGoToPosInc.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_start.svg'))
        self.ui.btnStop.setText('')
        self.ui.btnStop.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_stop.svg'))
        self.ui.btnHome.setText('')
        self.ui.btnHome.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/go-home.svg'))
        self.ui.btnCfg.setText('')
        self.ui.btnCfg.setIcon(taurus.qt.qtgui.resource.getIcon(':/categories/preferences-system.svg'))
        #################################################################################################################


        self.ui.motorGroupBox.setContextMenuPolicy(Qt.Qt.CustomContextMenu)
        self.connect(self.ui.motorGroupBox, Qt.SIGNAL('customContextMenuRequested(QPoint)'), self.buildContextMenu)

        self.connect(self.ui.btnGoToNeg, Qt.SIGNAL('clicked()'), self.jogNeg)
        self.connect(self.ui.btnGoToNegPress, Qt.SIGNAL('pressed()'), self.jogNeg)
        self.connect(self.ui.btnGoToNegPress, Qt.SIGNAL('released()'), self.abort)
        self.connect(self.ui.btnGoToNegInc, Qt.SIGNAL('clicked()'), self.goToNegInc)
        self.connect(self.ui.btnGoToPos, Qt.SIGNAL('clicked()'), self.jogPos)
        self.connect(self.ui.btnGoToPosPress, Qt.SIGNAL('pressed()'), self.jogPos)
        self.connect(self.ui.btnGoToPosPress, Qt.SIGNAL('released()'), self.abort)
        self.connect(self.ui.btnGoToPosInc, Qt.SIGNAL('clicked()'), self.goToPosInc)

        self.connect(self.ui.btnHome, Qt.SIGNAL('clicked()'), self.goHome)
        self.connect(self.ui.btnStop, Qt.SIGNAL('clicked()'), self.abort)

        # ALSO UPDATE THE WIDGETS EVERYTIME THE FORM HAS TO BE SHOWN
        self.connect(self.ui.btnCfg, Qt.SIGNAL('clicked()'), taurus_attr_form._updateAttrWidgets)
        self.connect(self.ui.btnCfg, Qt.SIGNAL('clicked()'), self.buildBetterCfgDialogTitle)

        #################################################################################################################
        ########################################
        # LET TAURUS CONFIGURATION MECANISM SHINE!
        ########################################
        self.registerConfigProperty(self.ui.inc.isVisible, self.toggleMoveRelative, 'MoveRelative')
        self.registerConfigProperty(self.ui.btnGoToNegPress.isVisible, self.toggleMoveContinuous, 'MoveContinuous')
        self.registerConfigProperty(self.ui.btnGoToNeg.isVisible, self.toggleMoveToLimits, 'MoveToLimits')
        self.registerConfigProperty(self.ui.btnStop.isVisible, self.toggleStopMove, 'StopMove')
        self.registerConfigProperty(self.ui.btnHome.isVisible, self.toggleHoming, 'Homing')
        self.registerConfigProperty(self.ui.btnCfg.isVisible, self.toggleConfig, 'Config')
        self.registerConfigProperty(self.ui.lblStatus.isVisible, self.toggleStatus, 'Status')
        #################################################################################################################

    #@Qt.pyqtSlot(list)
    def updateLimits(self, limits):
        if isinstance(limits, dict): limits = limits["limits"]
        pos_lim = limits[1]
        pos_btnstylesheet = ''
        enabled = True
        if pos_lim:
            pos_btnstylesheet = 'QPushButton{%s}'%taurus.core.util.DEVICE_STATE_PALETTE.qtStyleSheet(PyTango.DevState.ALARM)
            enabled = False
        self.ui.btnMax.setStyleSheet(pos_btnstylesheet)
        self.ui.btnGoToPos.setEnabled(enabled)
        self.ui.btnGoToPosPress.setEnabled(enabled)
        self.ui.btnGoToPosInc.setEnabled(enabled)


        neg_lim = limits[2]
        neg_btnstylesheet = ''
        enabled = True
        if neg_lim:
            neg_btnstylesheet = 'QPushButton{%s}'%taurus.core.util.DEVICE_STATE_PALETTE.qtStyleSheet(PyTango.DevState.ALARM)
            enabled = False
        self.ui.btnMin.setStyleSheet(neg_btnstylesheet)
        self.ui.btnGoToNeg.setEnabled(enabled)
        self.ui.btnGoToNegPress.setEnabled(enabled)
        self.ui.btnGoToNegInc.setEnabled(enabled)

    #def sizeHint(self):
    #    return Qt.QSize(300,30)

    def goToNegInc(self):
        self.moveInc(-1 * self.ui.inc.value())

    def goToPosInc(self):
        self.moveInc(self.ui.inc.value())

    def buildContextMenu(self, point):
        if not self.show_context_menu:
            return
        menu = Qt.QMenu(self)

        action_hide_all = Qt.QAction(self)
        action_hide_all.setText('Hide All')
        menu.addAction(action_hide_all)

        action_show_all = Qt.QAction(self)
        action_show_all.setText('Show All')
        menu.addAction(action_show_all)

        action_move_absolute = Qt.QAction(self)
        action_move_absolute.setText('Move Absolute')
        action_move_absolute.setCheckable(True)
        action_move_absolute.setChecked(self.taurus_value.writeWidget().isVisible())
        menu.addAction(action_move_absolute)

        action_move_relative = Qt.QAction(self)
        action_move_relative.setText('Move Relative')
        action_move_relative.setCheckable(True)
        action_move_relative.setChecked(self.ui.inc.isVisible())
        menu.addAction(action_move_relative)

        action_move_continuous = Qt.QAction(self)
        action_move_continuous.setText('Move Continuous')
        action_move_continuous.setCheckable(True)
        action_move_continuous.setChecked(self.ui.btnGoToNegPress.isVisible())
        menu.addAction(action_move_continuous)

        action_move_to_limits = Qt.QAction(self)
        action_move_to_limits.setText('Move to Limits')
        action_move_to_limits.setCheckable(True)
        action_move_to_limits.setChecked(self.ui.btnGoToNeg.isVisible())
        menu.addAction(action_move_to_limits)

        action_encoder = Qt.QAction(self)
        action_encoder.setText('Encoder Read')
        action_encoder.setCheckable(True)
        action_encoder.setChecked(self.taurus_value_enc.isVisible())
        if self.has_encoder:
            menu.addAction(action_encoder)

        action_stop_move = Qt.QAction(self)
        action_stop_move.setText('Stop Movement')
        action_stop_move.setCheckable(True)
        action_stop_move.setChecked(self.ui.btnStop.isVisible())
        menu.addAction(action_stop_move)

        action_homing = Qt.QAction(self)
        action_homing.setText('Homing')
        action_homing.setCheckable(True)
        action_homing.setChecked(self.ui.btnHome.isVisible())
        menu.addAction(action_homing)

        action_config = Qt.QAction(self)
        action_config.setText('Config')
        action_config.setCheckable(True)
        action_config.setChecked(self.ui.btnCfg.isVisible())
        menu.addAction(action_config)

        action_status = Qt.QAction(self)
        action_status.setText('Status')
        action_status.setCheckable(True)
        action_status.setChecked(self.ui.lblStatus.isVisible())
        menu.addAction(action_status)

        self.connect(action_hide_all, Qt.SIGNAL('triggered()'), self.toggleHideAll)
        self.connect(action_show_all, Qt.SIGNAL('triggered()'), self.toggleShowAll)
        self.connect(action_move_absolute, Qt.SIGNAL('toggled(bool)'), self.toggleMoveAbsolute)
        self.connect(action_move_relative, Qt.SIGNAL('toggled(bool)'), self.toggleMoveRelative)
        self.connect(action_move_continuous, Qt.SIGNAL('toggled(bool)'), self.toggleMoveContinuous)
        self.connect(action_move_to_limits, Qt.SIGNAL('toggled(bool)'), self.toggleMoveToLimits)
        self.connect(action_encoder, Qt.SIGNAL('toggled(bool)'), self.toggleEncoder)
        self.connect(action_stop_move, Qt.SIGNAL('toggled(bool)'), self.toggleStopMove)
        self.connect(action_homing, Qt.SIGNAL('toggled(bool)'), self.toggleHoming)
        self.connect(action_config, Qt.SIGNAL('toggled(bool)'), self.toggleConfig)
        self.connect(action_status, Qt.SIGNAL('toggled(bool)'), self.toggleStatus)

        menu.popup(self.cursor().pos())

    def toggleHideAll(self):
        self.toggleAll(False)

    def toggleShowAll(self):
        self.toggleAll(True)

    def toggleAll(self, visible):
        self.toggleMoveAbsolute(visible)
        self.toggleMoveRelative(visible)
        self.toggleMoveContinuous(visible)
        self.toggleMoveToLimits(visible)
        self.toggleEncoder(visible)
        self.toggleStopMove(visible)
        self.toggleHoming(visible)
        self.toggleConfig(visible)
        self.toggleStatus(visible)

    def toggleMoveAbsolute(self, visible):
        if self.taurus_value.writeWidget() is not None:
            self.taurus_value.writeWidget().setVisible(visible)

    def toggleMoveRelative(self, visible):
        self.ui.btnGoToNegInc.setVisible(visible)
        self.ui.inc.setVisible(visible)
        self.ui.btnGoToPosInc.setVisible(visible)

    def toggleMoveContinuous(self, visible):
        self.ui.btnGoToNegPress.setVisible(visible)
        self.ui.btnGoToPosPress.setVisible(visible)

    def toggleMoveToLimits(self, visible):
        self.ui.btnGoToNeg.setVisible(visible)
        self.ui.btnGoToPos.setVisible(visible)

    def toggleEncoder(self, visible):
        self.taurus_value_enc.setVisible(visible)

    def toggleStopMove(self, visible):
        self.ui.btnStop.setVisible(visible)

    def toggleHoming(self, visible):
        self.ui.btnHome.setVisible(visible)

    def toggleConfig(self, visible):
        self.ui.btnCfg.setVisible(visible)

    def toggleStatus(self, visible):
        self.ui.lblStatus.setVisible(visible)

    def dragEnterEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        mimeData = event.mimeData()
        if mimeData.hasFormat(taurus.qt.qtcore.mimetypes.TAURUS_DEV_MIME_TYPE):
            model = str(mimeData.data(taurus.qt.qtcore.mimetypes.TAURUS_DEV_MIME_TYPE))
        elif mimeData.hasFormat(taurus.qt.qtcore.mimetypes.TAURUS_ATTR_MIME_TYPE):
            model = str(mimeData.data(taurus.qt.qtcore.mimetypes.TAURUS_ATTR_MIME_TYPE))
        else:
            model = str(mimeData.text())
        self.setModel(model)

    def keyPressEvent(self, key_event):
        if key_event.key() == Qt.Qt.Key_Escape:
            self.abort()
            key_event.accept()
        TaurusWidget.keyPressEvent(self, key_event)

    def buildBetterCfgDialogTitle(self):
        while self.ui.btnCfg._dialog is None:
            pass
        model = self.getModel()
        self.ui.btnCfg._dialog.setWindowTitle('%s config'%taurus.Factory().getDevice(model).getSimpleName())

    @classmethod
    def getQtDesignerPluginInfo(cls):
        ret = TaurusBaseWidget.getQtDesignerPluginInfo()
        ret['module'] = 'taurus.qt.qtgui.extra_pool'
        ret['group'] = 'Taurus Extra Sardana'
        ret['icon'] = ':/designer/extra_pool.png'
        ret['container'] = False
        return ret

    def showEvent(self, event):
        TaurusWidget.showEvent(self, event)
        self.motor_dev.getAttribute('Position').enablePolling(force=True)

    def hideEvent(self, event):
        TaurusWidget.hideEvent(self, event)
        self.motor_dev.getAttribute('Position').disablePolling()

    #-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-
    # QT properties 
    #-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-
    @Qt.pyqtSignature("getModel()")
    def getModel(self):
        return self.ui.motorGroupBox.getModel()

    @Qt.pyqtSignature("setModel(QString)")
    def setModel(self, model):
        # DUE TO A BUG IN TAUGROUPBOX, WE NEED THE FULL MODEL NAME
        try:
            # In case the model is an attribute of a motor, get the device name
            if not taurus.core.DeviceNameValidator().isValid(model):
                model = model.rpartition('/')[0]
            model = taurus.Factory().getDevice(model).getFullName()
            self.setMotor(model)
            self.ui.motorGroupBox.setModel(model)
            self.ui.motorGroupBox.setEnabled(True)

            self.taurus_value.setModel(model+'/Position')

            # DUE TO A BUG IN TAURUSVALUE, THAT DO NOT USE PARENT MODEL WE NEED TO ALWAYS SET THE MODEL
            self.taurus_value.setUseParentModel(False)

            # THE FORCED APPLY HAS TO BE DONE AFTER THE MODEL IS SET, SO THE WRITEWIDGET IS AVAILABLE
            if self.taurus_value.writeWidget() is not None:
                self.taurus_value.writeWidget().setForcedApply(True)

            show_enc = self.taurus_value_enc.isVisible()
            if self.has_encoder:
                self.taurus_value_enc.setModel(model+'/Encoder')
                self.taurus_value_enc.setUseParentModel(False)
                self.taurus_value_enc.readWidget().setBgRole('none')
            else:
                self.taurus_value_enc.setModel(None)
                show_enc = False
            if not show_enc:
                self.toggleEncoder(False)

            try:
                self.unregisterConfigurableItem('MoveAbsolute')
                self.unregisterConfigurableItem('Encoder')
            except:
                pass
            self.registerConfigProperty(self.taurus_value.writeWidget().isVisible, self.toggleMoveAbsolute, 'MoveAbsolute')
            self.registerConfigProperty(self.taurus_value_enc.isVisible, self.toggleEncoder, 'Encoder')


            # SINCE TAURUSLAUNCHERBUTTON HAS NOT THIS PROPERTY IN THE
            # DESIGNER, WE MUST SET IT HERE
            self.ui.btnCfg.setUseParentModel(True)

            # CONFIGURE A LISTENER IN ORDER TO UPDATE LIMIT SWITCHES STATES
            self.limits_listener = LimitsListener()
            self.connect(self.limits_listener, Qt.SIGNAL('updateLimits(PyQt_PyObject)'), self.updateLimits)
            limits_visible = False
            if self.has_limits:
                limits_attribute = self.motor_dev.getAttribute('Limit_switches')
                limits_attribute.addListener(self.limits_listener)
                #self.updateLimits(limits_attribute.read().value)
                limits_visible = True
            self.ui.btnMin.setVisible(limits_visible)
            self.ui.btnMax.setVisible(limits_visible)
        except Exception,e:
            self.ui.motorGroupBox.setEnabled(False)
            self.info('Error setting model "%s". Reason: %s'%(model, repr(e)))
            self.traceback()

    @Qt.pyqtSignature("resetModel()")
    def resetModel(self):
        self.ui.motorGroupBox.resetModel()

    @Qt.pyqtSignature("getShowContextMenu()")
    def getShowContextMenu(self):
        return self.show_context_menu

    @Qt.pyqtSignature("setShowContextMenu(bool)")
    def setShowContextMenu(self, showContextMenu):
        self.show_context_menu = showContextMenu

    @Qt.pyqtSignature("resetShowContextMenu()")
    def resetShowContextMenu(self):
        self.show_context_menu = True

    @Qt.pyqtSignature("getStepSize()")
    def getStepSize(self):
        return self.ui.inc.value()

    @Qt.pyqtSignature("setStepSize(double)")
    def setStepSize(self, stepSize):
        self.ui.inc.setValue(stepSize)

    @Qt.pyqtSignature("resetStepSize()")
    def resetStepSize(self):
        self.setStepSize(1)

    @Qt.pyqtSignature("getStepSizeIncrement()")
    def getStepSizeIncrement(self):
        return self.ui.inc.singleStep()

    @Qt.pyqtSignature("setStepSizeIncrement(double)")
    def setStepSizeIncrement(self, stepSizeIncrement):
        self.ui.inc.setSingleStep(stepSizeIncrement)

    @Qt.pyqtSignature("resetStepSizeIncrement()")
    def resetStepSizeIncrement(self):
        self.setStepSizeIncrement(1)

    model = Qt.pyqtProperty("QString", getModel,setModel,resetModel)
    stepSize = Qt.pyqtProperty("double", getStepSize,setStepSize,resetStepSize)
    stepSizeIncrement = Qt.pyqtProperty("double", getStepSizeIncrement,setStepSizeIncrement,resetStepSizeIncrement)



################################################################################################
# NEW APPROACH TO OPERATE POOL MOTORS FROM A TAURUS FORM INHERITTING DIRECTLY FROM TaurusVALUE #
# AND USING PARTICULAR CLASSES THAT KNOW THEY ARE PART OF A TAURUSVALUE AND CAN INTERACT       #
################################################################################################

##################################################
#                  LABEL WIDGET                  #
##################################################
class PoolMotorTVLabelWidget(TaurusWidget):
    '''
    @TODO tooltip should be extended with status info
    @TODO context menu should be the lbl_alias extended
    @TODO default tooltip extended with the complete (multiline) status
    @TODO rightclick popup menu with actions: (1) switch user/expert view, (2) Config -all attributes-, (3) change motor
    For the (3), a drop event should accept if it is a device, and add it to the 'change-motor' list and select
    @TODO on the 'expert' row, it could be an ENABLE section with a button to set PowerOn to True/False
    '''
    def __init__(self, parent=None, designMode=False):
        TaurusWidget.__init__(self, parent, designMode)
        self.setLayout(Qt.QGridLayout())
        self.layout().setMargin(0)
        self.layout().setSpacing(0)

        self.lbl_alias = DefaultLabelWidget(parent, designMode)
        self.lbl_alias.setBgRole('none')
        self.layout().addWidget(self.lbl_alias)

        self.btn_poweron = Qt.QPushButton()
        self.btn_poweron.setEnabled(False)
        self.btn_poweron.setText('power on/off')
        self.layout().addWidget(self.btn_poweron)

        # Align everything on top
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Minimum, Qt.QSizePolicy.Expanding))

        # I don't like this approach, there should be something like
        # self.lbl_alias.addAction(...)
        self.lbl_alias.contextMenuEvent = lambda(event): self.contextMenuEvent(event)

        # I' don't like this approach, tehre should be something like
        # self.lbl_alias.addToolTipCallback(self.calculate_extra_tooltip)
        self.lbl_alias.getFormatedToolTip = self.calculateExtendedTooltip

    def setExpertView(self, expertView):
        btn_poweron_visible = expertView and self.taurusValueBuddy().hasPowerOn()
        self.btn_poweron.setVisible(btn_poweron_visible)

    def setModel(self, model):
        TaurusWidget.setModel(self, model+'/Status')
        self.lbl_alias.taurusValueBuddy = self.taurusValueBuddy
        self.lbl_alias.setModel(model)

        # Handle User/Expert view
        self.connect(self.taurusValueBuddy(), Qt.SIGNAL('expertViewChanged(bool)'), self.setExpertView)

    def calculateExtendedTooltip(self, cache=False):
        default_label_widget_tooltip = DefaultLabelWidget.getFormatedToolTip(self.lbl_alias, cache)
        status_info = ''
        motor_dev = self.taurusValueBuddy().motor_dev
        if motor_dev is not None:
            status = motor_dev.getAttribute('Status').read().value
            status_info = '<BR><B>Status</B>: '+status
        return default_label_widget_tooltip + status_info

    def contextMenuEvent(self, event):
        # Overwrite the default taurus label behaviour
        menu = Qt.QMenu(self)
        action_expert_view = Qt.QAction(self)
        action_expert_view.setText('Expert View')
        action_expert_view.setCheckable(True)
        action_expert_view.setChecked(self.taurusValueBuddy()._expertView)
        menu.addAction(action_expert_view)
        self.connect(action_expert_view, Qt.SIGNAL('toggled(bool)'), self.taurusValueBuddy().setExpertView)
        menu.exec_(event.globalPos())
        event.accept()

##################################################
#                   READ WIDGET                  #
##################################################
class PoolMotorTVReadWidget(TaurusWidget):
    '''
    @TODO on the 'expert' row, there should be an Indexer/Encoder radiobuttongroup to show units from raw dial/indx/enc
    @TODO TaurusLCD may be used but, now it does not display the sign, and color is WHITE... 
    '''
    def __init__(self, parent = None, designMode = False):
        TaurusWidget.__init__(self, parent, designMode)
        self.setLayout(Qt.QGridLayout())
        self.layout().setMargin(0)
        self.layout().setSpacing(0)

        self.lbl_read = TaurusLabel()
        self.lbl_read.setBgRole('quality')
        self.layout().addWidget(self.lbl_read)

        # Align everything on top
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Minimum, Qt.QSizePolicy.Expanding))

    def setExpertView(self, expertView):
        pass

    def setModel(self, model):
        TaurusWidget.setModel(self, model+'/Position')
        self.lbl_read.setModel(model+'/Position')

        # Handle User/Expert view
        self.connect(self.taurusValueBuddy(), Qt.SIGNAL('expertViewChanged(bool)'), self.setExpertView)

##################################################
#                  WRITE WIDGET                  #
##################################################
class PoolMotorTVWriteWidget(TaurusWidget):
    def __init__(self, parent = None, designMode = False):
        TaurusWidget.__init__(self, parent, designMode)
        self.setLayout(Qt.QGridLayout())
        self.layout().setMargin(0)
        self.layout().setSpacing(0)

        self.tabs_absolute_relative = Qt.QTabWidget()

        self.le_write_absolute = TaurusValueLineEdit()
        self.layout().addWidget(self.le_write_absolute, 0, 0, 1, 4)

        self.qw_write_relative = Qt.QWidget()
        self.qw_write_relative.setLayout(Qt.QHBoxLayout())
        self.qw_write_relative.layout().setMargin(0)
        self.qw_write_relative.layout().setSpacing(0)

        self.cb_step = Qt.QComboBox()
        self.cb_step.setSizePolicy(Qt.QSizePolicy(Qt.QSizePolicy.Expanding, Qt.QSizePolicy.Fixed))
        self.cb_step.setEditable(True)
        self.cb_step.lineEdit().setValidator(Qt.QDoubleValidator(self))
        self.cb_step.lineEdit().setAlignment(Qt.Qt.AlignRight)
        self.cb_step.addItem('1')
        self.qw_write_relative.layout().addWidget(self.cb_step)

        self.btn_step_down = Qt.QPushButton()
        self.btn_step_down.setToolTip('Decrements motor position')
        self.prepare_button(self.btn_step_down)
        self.btn_step_down.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_backward.svg'))
        self.qw_write_relative.layout().addWidget(self.btn_step_down)

        self.btn_step_up = Qt.QPushButton()
        self.btn_step_up.setToolTip('Increments motor position')
        self.prepare_button(self.btn_step_up)
        self.btn_step_up.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_start.svg'))
        self.qw_write_relative.layout().addWidget(self.btn_step_up)

        self.layout().addWidget(self.qw_write_relative, 0, 0, 1, 4)

        self.btn_stop = Qt.QPushButton()
        self.btn_stop.setToolTip('Stops de motor')
        self.prepare_button(self.btn_stop)
        self.btn_stop.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_stop.svg'))
        self.layout().addWidget(self.btn_stop, 0, 4)

        btns_layout = Qt.QHBoxLayout()
        btns_layout.setMargin(0)
        btns_layout.setSpacing(0)

        self.rbtn_absolute = Qt.QRadioButton('Absolute')
        self.rbtn_relative = Qt.QRadioButton('Relative')
        self.btngrp_absolute_relative = Qt.QButtonGroup()
        self.btngrp_absolute_relative.addButton(self.rbtn_absolute)
        self.btngrp_absolute_relative.addButton(self.rbtn_relative)
        #abs_rel_layout = Qt.QHBoxLayout()
        #abs_rel_layout.setMargin(10)
        #abs_rel_layout.setSpacing(0)
        #abs_rel_layout.addWidget(self.rbtn_absolute)
        #abs_rel_layout.addWidget(self.rbtn_relative)
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Expanding, Qt.QSizePolicy.Minimum), 1, 0)
        #self.layout().addLayout(abs_rel_layout, 1, 1)
        self.layout().addWidget(self.rbtn_absolute, 1, 1)
        self.layout().addWidget(self.rbtn_relative, 1, 2)
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Expanding, Qt.QSizePolicy.Minimum), 1, 3, 1, 1)

        # Since they belong in a button group, only one signal needed
        self.connect(self.rbtn_absolute, Qt.SIGNAL('toggled(bool)'), self.btnAbsoluteToggled)
        self.rbtn_absolute.setChecked(True)

        self.btn_lim_neg = Qt.QPushButton()
        self.btn_lim_neg.setToolTip('Negative Hardware Limit')
        self.btn_lim_neg.setEnabled(False)
        self.prepare_button(self.btn_lim_neg)
        self.btn_lim_neg.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/list-remove.svg'))
        btns_layout.addWidget(self.btn_lim_neg)

        self.btn_to_neg = Qt.QPushButton()
        self.btn_to_neg.setToolTip('Moves the motor towards the Negative Software Limit')
        self.prepare_button(self.btn_to_neg)
        self.btn_to_neg.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_skip_backward.svg'))
        btns_layout.addWidget(self.btn_to_neg)

        self.btn_to_neg_press = Qt.QPushButton()
        self.btn_to_neg_press.setToolTip('Moves the motor (while pressed) towards the Negative Software Limit')
        self.prepare_button(self.btn_to_neg_press)
        self.btn_to_neg_press.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_seek_backward.svg'))
        btns_layout.addWidget(self.btn_to_neg_press)

        self.btn_to_pos_press = Qt.QPushButton()
        self.prepare_button(self.btn_to_pos_press)
        self.btn_to_pos_press.setToolTip('Moves the motor (while pressed) towards the Positive Software Limit')
        self.btn_to_pos_press.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_seek_forward.svg'))
        btns_layout.addWidget(self.btn_to_pos_press)

        self.btn_to_pos = Qt.QPushButton()
        self.btn_to_pos.setToolTip('Moves the motor towards the Positive Software Limit')
        self.prepare_button(self.btn_to_pos)
        self.btn_to_pos.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_skip_forward.svg'))
        btns_layout.addWidget(self.btn_to_pos)

        self.btn_lim_pos = Qt.QPushButton()
        self.btn_lim_pos.setToolTip('Positive Hardware Limit')
        self.btn_lim_pos.setEnabled(False)
        self.prepare_button(self.btn_lim_pos)
        self.btn_lim_pos.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/list-add.svg'))
        btns_layout.addWidget(self.btn_lim_pos)

        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Expanding, Qt.QSizePolicy.Minimum), 2, 0)
        self.layout().addLayout(btns_layout, 2, 1, 1, 2)
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Expanding, Qt.QSizePolicy.Minimum), 2, 3, 1, 1)

        self.connect(self.btn_step_down, Qt.SIGNAL('clicked()'), self.stepDown)
        self.connect(self.btn_step_up, Qt.SIGNAL('clicked()'), self.stepUp)
        self.connect(self.btn_stop, Qt.SIGNAL('clicked()'), self.abort)
        self.connect(self.btn_to_neg, Qt.SIGNAL('clicked()'), self.goNegative)
        self.connect(self.btn_to_neg_press, Qt.SIGNAL('pressed()'), self.goNegative)
        self.connect(self.btn_to_neg_press, Qt.SIGNAL('released()'), self.abort)
        self.connect(self.btn_to_pos, Qt.SIGNAL('clicked()'), self.goPositive)
        self.connect(self.btn_to_pos_press, Qt.SIGNAL('pressed()'), self.goPositive)
        self.connect(self.btn_to_pos_press, Qt.SIGNAL('released()'), self.abort)

        # Align everything on top
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Minimum, Qt.QSizePolicy.Expanding), 3, 0, 1, 4)
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Minimum, Qt.QSizePolicy.Expanding), 1, 4, 3, 1)

    def btnAbsoluteToggled(self, checked):
        self.le_write_absolute.setVisible(checked)
        self.qw_write_relative.setVisible(not checked)

    def stepDown(self):
        self.goRelative(-1)

    def stepUp(self):
        self.goRelative(+1)

    @ProtectTaurusMessageBox(msg='An error occurred trying to move the motor.')
    def goRelative(self, direction):
        motor_dev = self.taurusValueBuddy().motor_dev
        if motor_dev is not None:
            increment = direction * float(self.cb_step.currentText())
            position = float(motor_dev.getAttribute('Position').read().value)
            target_position = position + increment
            motor_dev.getAttribute('Position').write(target_position)

    @ProtectTaurusMessageBox(msg='An error occurred trying to move the motor.')
    def goNegative(self):
        motor_dev = self.taurusValueBuddy().motor_dev
        if motor_dev is not None:
            min_value = float(motor_dev.getAttribute('Position').min_value)
            motor_dev.getAttribute('Position').write(min_value)

    @ProtectTaurusMessageBox(msg='An error occurred trying to move the motor.')
    def goPositive(self):
        motor_dev = self.taurusValueBuddy().motor_dev
        if motor_dev is not None:
            max_value = float(motor_dev.getAttribute('Position').max_value)
            motor_dev.getAttribute('Position').write(max_value)

    @ProtectTaurusMessageBox(msg='An error occurred trying to abort the motion.')
    def abort(self):
        motor_dev = self.taurusValueBuddy().motor_dev
        if motor_dev is not None:
            motor_dev.abort()

    def prepare_button(self, btn):
        btn_policy = Qt.QSizePolicy(Qt.QSizePolicy.Fixed, Qt.QSizePolicy.Fixed)
        btn_policy.setHorizontalStretch(0)
        btn_policy.setVerticalStretch(0)
        btn.setSizePolicy(btn_policy)
        btn.setMinimumSize(25, 25)
        btn.setMaximumSize(25, 25)
        btn.setText('')

    def setExpertView(self, expertView):
        self.btn_lim_neg.setVisible(expertView)
        self.btn_lim_pos.setVisible(expertView)

        self.btn_to_neg.setVisible(expertView)
        self.btn_to_neg_press.setVisible(expertView)

        self.btn_to_pos.setVisible(expertView)
        self.btn_to_pos_press.setVisible(expertView)

        if expertView and self.taurusValueBuddy().motor_dev is not None:
            hw_limits = self.taurusValueBuddy().hasHwLimits()
            self.btn_lim_neg.setVisible(hw_limits)
            self.btn_lim_pos.setVisible(hw_limits)

            neg_sw_limit_enabled = self.taurusValueBuddy().motor_dev.getAttribute('Position').min_value.lower() != 'not specified'
            self.btn_to_neg.setEnabled(neg_sw_limit_enabled)
            self.btn_to_neg_press.setEnabled(neg_sw_limit_enabled)

            pos_sw_limit_enabled = self.taurusValueBuddy().motor_dev.getAttribute('Position').max_value.lower() != 'not specified'
            self.btn_to_pos.setEnabled(pos_sw_limit_enabled)
            self.btn_to_pos_press.setEnabled(pos_sw_limit_enabled)

    def setModel(self, model):
        TaurusWidget.setModel(self, model+'/Position')
        self.le_write_absolute.setModel(model+'/Position')

        # Handle User/Expert View
        self.connect(self.taurusValueBuddy(), Qt.SIGNAL('expertViewChanged(bool)'), self.setExpertView)


    def keyPressEvent(self, key_event):
        if key_event.key() == Qt.Qt.Key_Escape:
            self.abort()
            key_event.accept()
        TaurusWidget.keyPressEvent(self, key_event)

##################################################
#                  UNITS WIDGET                  #
##################################################
class PoolMotorTVUnitsWidget(TaurusWidget):
    def __init__(self, parent=None, designMode=False):
        TaurusWidget.__init__(self, parent, designMode)
        self.setLayout(Qt.QGridLayout())
        self.layout().setMargin(0)
        self.layout().setSpacing(0)

        self.lbl_unit = DefaultUnitsWidget(parent, designMode)
        self.layout().addWidget(self.lbl_unit)

        # Align everything on top
        self.layout().addItem(Qt.QSpacerItem(1, 1, Qt.QSizePolicy.Minimum, Qt.QSizePolicy.Expanding))

    def setExpertView(self, expertView):
        pass

    def setModel(self, model):
        TaurusWidget.setModel(self, model+'/Position')
        self.lbl_unit.taurusValueBuddy = self.taurusValueBuddy
        self.lbl_unit.setModel(model+'/Position')
        # Handle User/Expert view
        self.connect(self.taurusValueBuddy(), Qt.SIGNAL('expertViewChanged(bool)'), self.setExpertView)

##################################################
#                TV MOTOR WIDGET                 #
##################################################
class PoolMotorTV(TaurusValue):
    ''' A widget that displays and controls a pool Motor device.  It
    behaves as a TaurusValue.
    @TODO the view mode should be stored in the configuration
    @TODO the motor list should be stored in the configuration
    @TODO the selected radiobuttons (dial/indx/enc) and (abs/rel) should be stored in configuration
    '''
    def __init__(self, parent = None, designMode = False):
        TaurusValue.__init__(self, parent = parent, designMode = designMode)
        self.setLabelWidgetClass(PoolMotorTVLabelWidget)
        self.setReadWidgetClass(PoolMotorTVReadWidget)
        self.setWriteWidgetClass(PoolMotorTVWriteWidget)
        self.setUnitsWidgetClass(PoolMotorTVUnitsWidget)

        self.setLabelConfig('dev_alias')

        self.motor_dev = None
        self._expertView = False
        self.limits_listener = None
        self.setExpertView(False)

    def setExpertView(self, expertView):
        self._expertView = expertView
        self.emit(Qt.SIGNAL('expertViewChanged(bool)'), expertView)
    
    def minimumHeight(self):
        return None #@todo: UGLY HACK to avoid subwidgets being forced to minimumheight=20
            
    def setModel(self, model):
        self.motor_dev = None
        TaurusValue.setModel(self, model)
        try:
            self.motor_dev = taurus.Device(model)
            # CONFIGURE A LISTENER IN ORDER TO UPDATE LIMIT SWITCHES STATES
            if self.limits_listener is not None:
                self.limits_listener.disconnect(self, Qt.SIGNAL('updateLimits(PyQt_PyObject)'))
            self.limits_listener = LimitsListener()
            if self.hasHwLimits():
                self.connect(self.limits_listener, Qt.SIGNAL('updateLimits(PyQt_PyObject)'), self.updateLimits)
                self.motor_dev.getAttribute('Limit_Switches').addListener(self.limits_listener)
        except Exception,e:
            print e
            return

    def hasPowerOn(self):
        try: return hasattr(self.motor_dev, 'PowerOn')
        except: return False

    def hasHwLimits(self):
        try: return hasattr(self.motor_dev, 'Limit_Switches')
        except: return False

    def updateLimits(self, limits):
        if isinstance(limits, dict): limits = limits["limits"]
        pos_lim = limits[1]
        pos_btnstylesheet = ''
        enabled = True
        if pos_lim:
            pos_btnstylesheet = 'QPushButton{%s}'%taurus.core.util.DEVICE_STATE_PALETTE.qtStyleSheet(PyTango.DevState.ALARM)
            enabled = False
        self.writeWidget().btn_step_up.setEnabled(enabled)
        self.writeWidget().btn_step_up.setStyleSheet(pos_btnstylesheet)
        self.writeWidget().btn_lim_pos.setStyleSheet(pos_btnstylesheet)
        self.writeWidget().btn_to_pos.setEnabled(enabled)
        self.writeWidget().btn_to_pos_press.setEnabled(enabled)

        neg_lim = limits[2]
        neg_btnstylesheet = ''
        enabled = True
        if neg_lim:
            neg_btnstylesheet = 'QPushButton{%s}'%taurus.core.util.DEVICE_STATE_PALETTE.qtStyleSheet(PyTango.DevState.ALARM)
            enabled = False
        self.writeWidget().btn_step_down.setEnabled(enabled)
        self.writeWidget().btn_step_down.setStyleSheet(neg_btnstylesheet)

        self.writeWidget().btn_lim_neg.setStyleSheet(neg_btnstylesheet)
        self.writeWidget().btn_to_neg.setEnabled(enabled)
        self.writeWidget().btn_to_neg_press.setEnabled(enabled)

    def showEvent(self, event):
        TaurusValue.showEvent(self, event)
        if self.motor_dev is not None:
            self.motor_dev.getAttribute('Position').enablePolling(force=True)

    def hideEvent(self, event):
        TaurusValue.hideEvent(self, event)
        if self.motor_dev is not None:
            self.motor_dev.getAttribute('Position').disablePolling()

###################################################
# A SIMPLER WIDGET THAT MAY BE USED OUTSIDE FORMS #
###################################################

class PoolMotor(TaurusWidget):
    ''' A widget that displays and controls a pool Motor device.
    NOTE: WHEN GETTING EVENTS ON LIMITS, SOMETHING SHOULD BE DONE LIKE:
    setStyleSheet('QAbstractSpinBox::up-button {background-color: orange;} QAbstractSpinBox::down-button {background-color: red;}')
    '''
    def __init__(self, parent = None, designMode = False):
        TaurusWidget.__init__(self, parent, designMode)

        self.motor_dev = None

        self.setLayout(Qt.QHBoxLayout())
        self.layout().setContentsMargins(0,0,0,0)
        self.layout().setSpacing(0)

        self.alias_label = TaurusLabel()
        self.alias_label.setBgRole('state')
        self.layout().addWidget(self.alias_label)

        self.read_label = TaurusLabel()
        self.layout().addWidget(self.read_label)

        self.write_spinbox = TaurusValueSpinBox()
        self.write_spinbox.setForcedApply(True)
        self.write_spinbox.setButtonSymbols(Qt.QAbstractSpinBox.PlusMinus)
        self.layout().addWidget(self.write_spinbox)

        self.unit_label = TaurusLabel()
        self.unit_label.setBgRole('none')
        self.layout().addWidget(self.unit_label)

        self.btn_stop = Qt.QPushButton()
        self.btn_stop.setIcon(taurus.qt.qtgui.resource.getIcon(':/actions/media_playback_stop.svg'))
        self.btn_stop.setFixedSize(self.btn_stop.iconSize())
        self.layout().addWidget(self.btn_stop)

        #### At some point it will be an icon...
        self.step_icon = Qt.QLabel('step')
        self.layout().addWidget(self.step_icon)

        self.cb_step = Qt.QComboBox()
        self.cb_step.addItem('1')
        self.cb_step.setEditable(True)
        self.cb_step.setFixedWidth(60)
        self.layout().addWidget(self.cb_step)

        self.connectSignals()

    def setModel(self, model):
        try: self.motor_dev = taurus.Device(model)
        except: return

        self.alias_label.setModel('%s/State?configuration=dev_alias' % model)
        self.read_label.setModel('%s/Position' % model)
        self.write_spinbox.setModel('%s/Position' % model)
        self.unit_label.setModel('%s/Position?configuration=unit' % model)

    def showEvent(self, event):
        TaurusWidget.showEvent(self, event)
        if self.motor_dev is not None:
            self.motor_dev.getAttribute('Position').enablePolling(force=True)

    def hideEvent(self, event):
        TaurusWidget.hideEvent(self, event)
        if self.motor_dev is not None:
            self.motor_dev.getAttribute('Position').disablePolling()

    def keyPressEvent(self, key_event):
        if key_event.key() == Qt.Qt.Key_Escape:
            self.abort()
            key_event.accept()
        TaurusWidget.keyPressEvent(self, key_event)

    def connectSignals(self):
        self.connect(self.btn_stop, Qt.SIGNAL('clicked()'), self.abort)
        self.connect(self.cb_step, Qt.SIGNAL('currentIndexChanged(QString)'), self.updateStepSize)

    @ProtectTaurusMessageBox(msg='An error occurred trying to abort the motion.')
    def abort(self):
        if self.motor_dev is None:
            return
        self.motor_dev.abort()

    def updateStepSize(self, value):
        try:
            value = float(value)
            self.write_spinbox.setSingleStep(value)
        except Exception,e:
            print 'oups',e


def main():

    import sys
    import taurus.qt.qtgui.application
    import taurus.core.util.argparse
    from taurus.qt.qtgui.panel import TaurusForm

    parser = taurus.core.util.argparse.get_taurus_parser()
    parser.usage = "%prog [options] [<motor1> [<motor2>] ...]"

    app = taurus.qt.qtgui.application.TaurusApplication(cmd_line_parser=parser)
    args = app.get_command_line_args()

    models = ['tango://controls02:10000/motor/gcipap10ctrl/8']
    if len(args)>0:
        models = args

    w = Qt.QWidget()
    w.setLayout(Qt.QVBoxLayout())


    tests = []
    #tests.append(1)
    tests.append(2)
    #tests.append(3)

    # 1) Test PoolMotorSlim motor widget
    form_pms = TaurusForm()
    pms_widget_class = 'taurus.qt.qtgui.extra_pool.PoolMotorSlim'
    pms_tgclass_map = {'SimuMotor':(pms_widget_class,(),{}),
                       'Motor':(pms_widget_class,(),{}),
                       'PseudoMotor':(pms_widget_class,(),{})}
    form_pms.setCustomWidgetMap(pms_tgclass_map)
    if 1 in tests:
        form_pms.setModel(models)
        w.layout().addWidget(form_pms)

    # 2) Test PoolMotorTV motor widget
    form_tv = TaurusForm()
    tv_widget_class = 'taurus.qt.qtgui.extra_pool.PoolMotorTV'
    tv_tgclass_map = {'SimuMotor':(tv_widget_class,(),{}),
                      'Motor':(tv_widget_class,(),{}),
                      'PseudoMotor':(tv_widget_class,(),{})}
    form_tv.setCustomWidgetMap(tv_tgclass_map)

    if 2 in tests:
        models.append('gc_ipap8/DialPosition')
        models.append('gc_ipap8/Sign')
        models.append('gc_ipap8/Offset')
        models.append('gc_ipap8/Position')
        models.append('gc_ipap8/State')
        form_tv.setModel(models)
        w.layout().addWidget(form_tv)


    # 3) Test Stand-Alone PoolMotor widget
    if 3 in tests:
        for motor in models:
            motor_widget = PoolMotor()
            motor_widget.setModel(motor)
            w.layout().addWidget(motor_widget)

    w.show()

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
