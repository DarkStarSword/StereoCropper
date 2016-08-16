#!/usr/bin/env python

# Copyright 2016 Ian Munsie
#
# This file is part of the Stereo Cropping Tool.
#
# The Stereo Cropping Tool is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# The Stereo Cropping Tool is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# The Stereo Cropping Tool. If not, see <http://www.gnu.org/licenses/>.

# http://stackoverflow.com/questions/13291783/how-to-get-the-id-memory-address-of-dll-function
# http://stackoverflow.com/questions/6165628/use-python-ctypes-to-interface-with-nvapi-follow-up-with-demonstration-code

import ctypes
from ctypes import *
from _ctypes import CFuncPtr

nvapi_ids = {
	'GetUnAttachedAssociatedDisplayName': 0x4888D790,
	'Stereo_Disable': 0x2EC50C2B,
	'GPU_GetPCIIdentifiers': 0x2DDFB66E,
	'GPU_GetECCErrorInfo': 0xC71F85A6,
	'Disp_InfoFrameControl': 0x6067AF3F,
	'Mosaic_GetCurrentTopo': 0xEC32944E,
	'Unload': 0xD22BDD7E,
	'EnableCurrentMosaicTopology': 0x74073CC9,
	'DRS_GetNumProfiles': 0x1DAE4FBC,
	'DRS_LoadSettingsFromFile': 0xD3EDE889,
	'Stereo_SetFrustumAdjustMode': 0x7BE27FA2,
	'Mosaic_SetCurrentTopo': 0x9B542831,
	'DRS_GetApplicationInfo': 0xED1F8C69,
	'Stereo_Activate': 0xF6A1AD68,
	'Stereo_GetFrustumAdjustMode': 0xE6839B43,
	'D3D_SetFPSIndicatorState': 0xA776E8DB,
	'GetLogicalGPUFromPhysicalGPU': 0xADD604D1,
	'GetAssociatedNvidiaDisplayName': 0x22A78B05,
	'GetViewEx': 0xDBBC0AF4,
	'Stereo_CapturePngImage': 0x8B7E99B5,
	'Stereo_GetSurfaceCreationMode': 0x36F1C736,
	'GPU_GetEDID': 0x37D32E69,
	'Stereo_CreateConfigurationProfileRegistryKey': 0xBE7692EC,
	'VIO_Status': 0x0E6CE4F1,
	'DRS_GetCurrentGlobalProfile': 0x617BFF9F,
	'VIO_GetPCIInfo': 0xB981D935,
	'GetSupportedMosaicTopologies': 0x410B5C25,
	'VIO_SetSyncDelay': 0x2697A8D1,
	'GPU_SetIllumination': 0x0254A187,
	'VIO_GetGamma': 0x51D53D06,
	'Disp_ColorControl': 0x92F9D80D,
	'GetSupportedViews': 0x66FB7FC0,
	'DRS_LoadSettings': 0x375DBD6B,
	'DRS_CreateApplication': 0x4347A9DE,
	'EnumLogicalGPUs': 0x48B3EA59,
	'Stereo_SetSurfaceCreationMode': 0xF5DCFCBA,
	'DISP_GetDisplayConfig': 0x11ABCCF8,
	'GetCurrentMosaicTopology': 0xF60852BD,
	'DisableHWCursor': 0xAB163097,
	'D3D9_AliasSurfaceAsTexture': 0xE5CEAE41,
	'GPU_GetBusSlotId': 0x2A0A350F,
	'GPU_GetTachReading': 0x5F608315,
	'Stereo_SetSeparation': 0x5C069FA3,
	'GPU_GetECCStatusInfo': 0xCA1DDAF3,
	'VIO_IsFrameLockModeCompatible': 0x7BF0A94D,
	'Mosaic_EnumDisplayGrids': 0xDF2887AF,
	'DISP_SetDisplayConfig': 0x5D8CF8DE,
	'DRS_EnumAvailableSettingIds': 0xF020614A,
	'VIO_SetConfig': 0x0E4EEC07,
	'GPU_GetPerfDecreaseInfo': 0x7F7F4600,
	'SYS_GetLidAndDockInfo': 0xCDA14D8A,
	'GPU_GetPstates20': 0x6FF81213,
	'GPU_GetAllOutputs': 0x7D554F8E,
	'GPU_GetConnectedSLIOutputs': 0x0680DE09,
	'VIO_IsRunning': 0x96BD040E,
	'Initialize': 0x0150E828,
	'VIO_Close': 0xD01BD237,
	'Stereo_GetStereoSupport': 0x296C434D,
	'GPU_GetGPUType': 0xC33BAEB1,
	'Stereo_CaptureJpegImage': 0x932CB140,
	'DRS_GetProfileInfo': 0x61CD6FD6,
	'Stereo_SetConfigurationProfileValue': 0x24409F48,
	'VIO_SyncFormatDetect': 0x118D48A3,
	'VIO_GetCapabilities': 0x1DC91303,
	'GPU_GetCurrentAGPRate': 0xC74925A0,
	'I2CWrite': 0xE812EB07,
	'Stereo_GetSeparation': 0x451F2134,
	'GPU_GetPstatesInfoEx': 0x843C0256,
	'DRS_SetCurrentGlobalProfile': 0x1C89C5DF,
	'Mosaic_GetTopoGroup': 0xCB89381D,
	'GPU_GetCurrentPCIEDownstreamWidth': 0xD048C3B1,
	'D3D9_RegisterResource': 0xA064BDFC,
	'DRS_RestoreProfileDefaultSetting': 0x53F0381E,
	'VIO_GetSyncDelay': 0x462214A9,
	'GPU_GetVbiosOEMRevision': 0x2D43FB31,
	'GetVBlankCounter': 0x67B5DB55,
	'GetDisplayDriverVersion': 0xF951A4D1,
	'DRS_EnumSettings': 0xAE3039DA,
	'GPU_QueryIlluminationSupport': 0xA629DA31,
	'GetLogicalGPUFromDisplay': 0xEE1370CF,
	'DRS_EnumApplications': 0x7FA2173A,
	'Mosaic_EnableCurrentTopo': 0x5F1AA66C,
	'Stereo_IsActivated': 0x1FB0BC30,
	'VIO_Stop': 0x6BA2A5D6,
	'SYS_GetChipSetInfo': 0x53DABBCA,
	'GPU_GetActiveOutputs': 0xE3E89B6F,
	'DRS_GetSettingNameFromId': 0xD61CBE6E,
	'GetPhysicalGPUFromUnAttachedDisplay': 0x5018ED61,
	'Mosaic_GetSupportedTopoInfo': 0xFDB63C81,
	'GPU_GetIRQ': 0xE4715417,
	'GPU_GetOutputType': 0x40A505E4,
	'Stereo_IsEnabled': 0x348FF8E1,
	'Stereo_Enable': 0x239C4545,
	'GPU_GetSystemType': 0xBAAABFCC,
	'GPU_SetEDID': 0xE83D6456,
	'GetPhysicalGPUsFromLogicalGPU': 0xAEA3FA32,
	'VIO_GetConfig': 0xD34A789B,
	'GetNvAPI_StatuserfaceVersionString': 0x01053FA5,
	'GPU_ResetECCErrorInfo': 0xC02EEC20,
	'SetCurrentMosaicTopology': 0xD54B8989,
	'DISP_GetDisplayIdByDisplayName': 0xAE457190,
	'GetView': 0xD6B99D89,
	'Stereo_DeleteConfigurationProfileRegistryKey': 0xF117B834,
	'DRS_DestroySession': 0xDAD9CFF8,
	'GPU_WorkstationFeatureQuery': 0x004537DF,
	'VIO_QueryTopology': 0x869534E2,
	'DRS_EnumAvailableSettingValues': 0x2EC39F90,
	'DRS_GetBaseProfile': 0xDA8466A0,
	'OGL_ExpertModeDefaultsGet': 0xAE921F12,
	'DRS_DeleteApplicationEx': 0xC5EA85A1,
	'D3D1x_CreateSwapChain': 0x1BC21B66,
	'GPU_GetConnectedDisplayIds': 0x0078DBA2,
	'DRS_FindProfileByName': 0x7E4A9A0B,
	'D3D9_UnregisterResource': 0xBB2B17AA,
	'DRS_EnumProfiles': 0xBC371EE0,
	'VIO_EnumDevices': 0xFD7C5557,
	'DRS_CreateProfile': 0xCC176068,
	'D3D9_StretchRectEx': 0x22DE03AA,
	'DRS_GetSetting': 0x73BF8338,
	'Stereo_InitActivation': 0xC7177702,
	'EnumNvidiaDisplayHandle': 0x9ABDD40D,
	'GPU_GetConnectedSLIOutputsWithLidState': 0x96043CC7,
	'Stereo_DecreaseConvergence': 0x4C87E317,
	'GPU_GetBusType': 0x1BB18724,
	'DRS_FindApplicationByName': 0xEEE566B2,
	'D3D9_ClearRT': 0x332D3942,
	'GPU_GetVirtualFrameBufferSize': 0x5A04B644,
	'GPU_GetAllDisplayIds': 0x785210A2,
	'DRS_SetSetting': 0x577DD202,
	'Stereo_GetConvergence': 0x4AB00934,
	'GPU_GetCurrentPstate': 0x927DA4F6,
	'VIO_SetCSC': 0xA1EC8D74,
	'CreateDisplayFromUnAttachedDisplay': 0x63F9799E,
	'DRS_SaveSettingsToFile': 0x2BE25DF8,
	'DRS_DeleteProfile': 0x17093206,
	'Stereo_Trigger_Activation': 0x0D6C6CD2,
	'GPU_GetThermalSettings': 0xE3640A56,
	'Stereo_SetNotificationMessage': 0x6B9B409E,
	'Stereo_CreateHandleFromIUnknown': 0xAC7E37F4,
	'Stereo_DecreaseSeparation': 0xDA044458,
	'GPU_ValidateOutputCombination': 0x34C9C2D4,
	'Stereo_ReverseStereoBlitControl': 0x3CD58F89,
	'GPU_GetConnectedOutputs': 0x1730BFC9,
	'DRS_GetSettingIdFromName': 0xCB7309CD,
	'EnumPhysicalGPUs': 0xE5AC921F,
	'VIO_GetCSC': 0x7B0D72A3,
	'GPU_GetVbiosRevision': 0xACC3DA0A,
	'SYS_GetDriverAndBranchVersion': 0x2926AAAD,
	'SetDisplayPort': 0xFA13E65A,
	'GPU_GetPhysicalFrameBufferSize': 0x46FBEB03,
	'DRS_CreateSession': 0x0694D52E,
	'VIO_EnumSignalFormats': 0xEAD72FE4,
	'GPU_GetECCConfigurationInfo': 0x77A796F3,
	'Mosaic_GetOverlapLimits': 0x989685F0,
	'GetHDMISupportInfo': 0x6AE16EC3,
	'Mosaic_EnumDisplayModes': 0x78DB97D7,
	'Stereo_DeleteConfigurationProfileValue': 0x49BCEECF,
	'OGL_ExpertModeSet': 0x3805EF7A,
	'GetPhysicalGPUsFromDisplay': 0x34EF9506,
	'Mosaic_GetDisplayViewportsByResolution': 0xDC6DC8D3,
	'VIO_Open': 0x44EE4841,
	'DRS_SaveSettings': 0xFCBC7E14,
	'D3D9_CreateSwapChain': 0x1A131E09,
	'GPU_GetHDCPSupportStatus': 0xF089EEF5,
	'DISP_GetAssociatedUnAttachedNvidiaDisplayHandle': 0xA70503B2,
	'Stereo_DestroyHandle': 0x3A153134,
	'DRS_RestoreAllDefaults': 0x5927B094,
	'VIO_SetGamma': 0x964BF452,
	'GPU_GetBoardInfo': 0x22D54523,
	'DRS_SetProfileInfo': 0x16ABD3A9,
	'DISP_GetGDIPrimaryDisplayId': 0x1E9D8A31,
	'Stereo_SetDriverMode': 0x5E8F0BEC,
	'D3D_GetCurrentSLIState': 0x4B708B54,
	'SetViewEx': 0x06B89E68,
	'I2CRead': 0x2FDE12C5,
	'DRS_RestoreProfileDefault': 0xFA5F6134,
	'GetDisplayPortInfo': 0xC64FF367,
	'VIO_Start': 0xCDE8E1A3,
	'OGL_ExpertModeGet': 0x22ED9516,
	'EnumNvidiaUnAttachedDisplayHandle': 0x20DE9260,
	'SYS_GetGpuAndOutputIdFromDisplayId': 0x112BA1A5,
	'Stereo_Deactivate': 0x2D68DE96,
	'GPU_GetFullName': 0xCEEE8E9F,
	'DRS_DeleteProfileSetting': 0xE4A26362,
	'OGL_ExpertModeDefaultsSet': 0xB47A657E,
	'GetErrorMessage': 0x6C2D048C,
	'SetRefreshRateOverride': 0x3092AC32,
	'Stereo_IncreaseSeparation': 0xC9A8ECEC,
	'GPU_GetGpuCoreCount': 0xC7026A87,
	'SYS_GetDisplayIdFromGpuAndOutputId': 0x08F2BAB4,
	'GPU_GetIllumination': 0x9A1B9365,
	'SetView': 0x0957D7B6,
	'GetAssociatedNvidiaDisplayHandle': 0x35C29134,
	'GPU_GetBusId': 0x1BE0B8E5,
	'DRS_DeleteApplication': 0x2C694BC6,
	'Stereo_SetActiveEye': 0x96EEA9F8,
	'GPU_GetAGPAperture': 0x6E042794,
	'GetAssociatedDisplayOutputId': 0xD995937E,
	'EnableHWCursor': 0x2863148D,
	'Stereo_GetEyeSeparation': 0xCE653127,
	'DISP_GetMonitorCapabilities': 0x3B05C7E1,
	'Stereo_SetConvergence': 0x3DD6B54B,
	'GPU_WorkstationFeatureSetup': 0x6C1F3FE4,
	'GPU_GetConnectedOutputsWithLidState': 0xCF8CAF39,
	'Stereo_IncreaseConvergence': 0xA17DAABE,
	'GPU_GetDynamicPstatesInfoEx': 0x60DED2ED,
	'GPU_GetVbiosVersionString': 0xA561FD7D,
	'GPU_SetECCConfiguration': 0x1CF639D9,
	'VIO_EnumDataFormats': 0x221FA8E8,
}

class NvAPI_Exception(Exception): pass

NvAPI_UnicodeString = c_uint16 * 2048

class STEREO_DRIVER_MODE(object):
	AUTOMATIC = 0
	DIRECT    = 2

class STEREO_ACTIVE_EYE(object):
	RIGHT = 1
	LEFT  = 2
	MONO  = 3

class NVDRS_SETTING(Structure):
	class VALUE(Union):
		class BinaryValue(Structure):
			_fields_ = [
				('valueLength', c_uint32),
				('valueData', c_uint8 * 4096),
			]
		_fields_ = [
			('u32Value', c_uint32),
			('binaryValue', BinaryValue),
			('wszValue', NvAPI_UnicodeString),
		]
	_fields_ = [
		('version', c_uint32),
		('settingName', NvAPI_UnicodeString),
		('settingId', c_uint32),
		('settingType', c_int),
		('settingLocation', c_int),
		('isCurrentPredefined', c_uint32),
		('isPredefinedValid', c_uint32),
		('predefined', VALUE),
		('current', VALUE),
	]

def MAKE_NVAPI_VERSION(struct, version):
	return sizeof(struct) | (version << 16)

class _NvAPI(object):
	nvapi_QueryInterface = cdll.nvapi.nvapi_QueryInterface

	class _nvapi_FuncPtr(CFuncPtr):
		_flags_ = ctypes._FUNCFLAG_CDECL
		_restype_ = c_int

	def get_error(self, status):
		szDesc = create_string_buffer(64)
		self.GetErrorMessage(status, szDesc)
		return szDesc

	def wrap_errors(self, fn):
		def f(*a, **kw):
			rc = fn(*a, **kw)
			if (rc):
				err = self.get_error(rc)
				raise NvAPI_Exception(err.value)
			return rc
		return f

	def __getattr__(self, name):
		id = nvapi_ids[name]
		ptr = self.nvapi_QueryInterface(id)
		f = self.wrap_errors(self._nvapi_FuncPtr(ptr))
		setattr(self, name, f)
		return f

NvAPI = _NvAPI()
