#!/usr/bin/env python2
# -*- coding: utf-8 -*-

#---------------------------------------
#   Import Libraries
#---------------------------------------
import logging
from logging.handlers import TimedRotatingFileHandler
import clr
import re
import os
import sys
import codecs
import json
import uuid
clr.AddReference("websocket-sharp.dll")
from WebSocketSharp import WebSocket
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
from EventTemplates import TwitchBits, TwitchSubscriptions, TwitchChannelPoints

#---------------------------------------
#   [Required] Script Information
#---------------------------------------
ScriptName = 'TwitchPubSubMirror'
Website = 'https://github.com/nossebro/TwitchPubSubMirror'
Creator = 'nossebro'
Version = '0.1.0'
Description = 'Mirrors events from Twitch PubSub socket, and sends them to a local SLCB-compatible websocket'

#---------------------------------------
#   Script Variables
#---------------------------------------
ScriptSettings = None
LocalSocket = None
LocalSocketIsConnected = False
TwitchPubSubAPI = None
TwitchPubSubAPIPong = True
Logger = None
SettingsFile = os.path.join(os.path.dirname(__file__), "Settings.json")
UIConfigFile = os.path.join(os.path.dirname(__file__), "UI_Config.json")

#---------------------------------------
#   Script Classes
#---------------------------------------
class StreamlabsLogHandler(logging.StreamHandler):
	def emit(self, record):
		try:
			message = self.format(record)
			Parent.Log(ScriptName, message)
			self.flush()
		except (KeyboardInterrupt, SystemExit):
			raise
		except:
			self.handleError(record)

class Settings(object):
	def __init__(self, settingsfile=None):
		defaults = self.DefaultSettings(UIConfigFile)
		try:
			with codecs.open(settingsfile, encoding="utf-8-sig", mode="r") as f:
				settings = json.load(f, encoding="utf-8")
			self.__dict__ = self.MergeSettings(defaults, settings)
		except:
			self.__dict__ = defaults

	def MergeSettings(self, x=dict(), y=dict()):
		z = x.copy()
		for attr in x:
			if attr in y:
				z[attr] = y[attr]
		return z

	def DefaultSettings(self, settingsfile=None):
		defaults = dict()
		with codecs.open(settingsfile, encoding="utf-8-sig", mode="r") as f:
			ui = json.load(f, encoding="utf-8")
		for key in ui:
			try:
				defaults[key] = ui[key]["value"]
			except:
				continue
		return defaults

	def Reload(self, jsondata):
		self.__dict__ = self.MergeSettings(self.DefaultSettings(UIConfigFile), json.loads(jsondata, encoding="utf-8"))
		self.SaveSettings(SettingsFile)

	def SaveSettings(self, settingsfile=None):
		defaults = self.DefaultSettings(UIConfigFile)
		self.__dict__ = self.MergeSettings(defaults, self.__dict__)
		try:
			with codecs.open(settingsfile, encoding="utf-8-sig", mode="w") as f:
				json.dump(self.__dict__, f, encoding="utf-8", indent=2)
			with codecs.open(settingsfile.replace("json", "js"), encoding="utf-8-sig", mode="w") as f:
				f.writelines("var settings = {0};".format(json.dumps(self.__dict__, encoding="utf-8", indent=2)))
		except:
			Parent.Log(ScriptName, "SaveSettings(): Could not write settings to file")

#---------------------------------------
#   Script Functions
#---------------------------------------
def GetLogger():
	log = logging.getLogger(ScriptName)
	log.setLevel(logging.DEBUG)

	sl = StreamlabsLogHandler()
	sl.setFormatter(logging.Formatter("%(funcName)s(): %(message)s"))
	sl.setLevel(logging.INFO)
	log.addHandler(sl)

	fl = TimedRotatingFileHandler(filename=os.path.join(os.path.dirname(__file__), "info"), when="w0", backupCount=8, encoding="utf-8")
	fl.suffix = "%Y%m%d"
	fl.setFormatter(logging.Formatter("%(asctime)s  %(funcName)s(): %(levelname)s: %(message)s"))
	fl.setLevel(logging.INFO)
	log.addHandler(fl)

	if ScriptSettings.DebugMode:
		dfl = TimedRotatingFileHandler(filename=os.path.join(os.path.dirname(__file__), "debug"), when="h", backupCount=24, encoding="utf-8")
		dfl.suffix = "%Y%m%d%H%M%S"
		dfl.setFormatter(logging.Formatter("%(asctime)s  %(funcName)s(): %(levelname)s: %(message)s"))
		dfl.setLevel(logging.DEBUG)
		log.addHandler(dfl)

	log.debug("Logger initialized")
	return log

def Nonce():
	nonce = uuid.uuid1()
	oauth_nonce = nonce.hex
	return oauth_nonce

def GetTwitchUserID(Username = None):
	global ScriptSettings
	global Logger
	ID = None
	if not ScriptSettings.JTVClientID or not ScriptSettings.JTVToken:
		return
	if not Username:
		Username = ScriptSettings.StreamerName
	Header = {
		"Client-ID": ScriptSettings.JTVClientID,
		"Authorization": "Bearer {0}".format(ScriptSettings.JTVToken)
	}
	Logger.debug("Header: {0}".format(json.dumps(Header)))
	try:
		result = json.loads(str.encode(Parent.GetRequest("https://api.twitch.tv/helix/users?login={0}".format(Username.lower()), Header), encoding="utf-8"))
		if result["status"] == 200:
			response = json.loads(result["response"])
			Logger.debug("Response: {0}".format(json.dumps(response)))
			ID = response["data"][0]["id"]
			Logger.debug("ID: {0}".format(ID))
		elif "error" in result:
			Logger.error("Error Code {0}: {1}".format(result["status"], result["error"]))
		else:
			Logger.warning("Response unknown: {0}".format(result))
	except Exception as e:
		Logger.debug(e, exc_info=True)
	return ID

def SendEvent(events):
	global Logger
	global ScriptSettings
	global LocalSocket
	for event in events:
		if any(x in event["event"] for x in ["EVENT_CHEER", "EVENT_DONATION", "EVENT_FOLLOW", "EVENT_HOST", "EVENT_SUB"]):
			if ScriptSettings.SLCBCompat:
				LocalSocket.Send(json.dumps(event))
				Logger.debug("Sending event via websocket: {0}".format(json.dumps(event, indent=4)))
		else:
			if ScriptSettings.SLCBBroadcast:
				Parent.BroadcastWsEvent(event["event"], json.dumps(event["data"]))
				Logger.debug("Sending event via SLCB: {0}".format(json.dumps(event, indent=4)))
			if ScriptSettings.LocalWebsocket:
				LocalSocket.Send(json.dumps(event))
				Logger.debug("Sending event via websocket: {0}".format(json.dumps(event, indent=4)))

def ArgsToDict(ArgsList, Dict):
	z = dict()
	for key in ArgsList:
		if key in [ "is_test", "is_repeat" ]:
			z[key] = False
			continue
		z[key] = Dict.get(key)
	Logger.debug(json.dumps(z, indent=4))
	return z

#---------------------------------------
#   Chatbot Initialize Function
#---------------------------------------
def Init():
	global ScriptSettings
	ScriptSettings = Settings(SettingsFile)
	global Logger
	Logger = GetLogger()
	Parent.BroadcastWsEvent('{0}_UPDATE_SETTINGS'.format(ScriptName.upper()), json.dumps(ScriptSettings.__dict__))
	Logger.debug(json.dumps(ScriptSettings.__dict__, indent=4))

	global LocalSocket
	if ScriptSettings.LocalWebsocket and ScriptSettings.LocalWebsocketPort:
		LocalSocket = WebSocket("ws://localhost:{0}/streamlabs".format(ScriptSettings.LocalWebsocketPort))
		LocalSocket.OnOpen += LocalSocketConnected
		LocalSocket.OnClose += LocalSocketDisconnected
		LocalSocket.OnMessage += LocalSocketEvent
		LocalSocket.OnError += LocalSocketError

	global TwitchPubSubAPI
	TwitchPubSubAPI = WebSocket("wss://pubsub-edge.twitch.tv")
	TwitchPubSubAPI.OnOpen += TwitchPubSubAPIConnected
	TwitchPubSubAPI.OnClose += TwitchPubSubAPIDisconnected
	TwitchPubSubAPI.OnMessage += TwitchPubSubAPIEvent
	TwitchPubSubAPI.OnError += TwitchPubSubAPIError

#---------------------------------------
#   Chatbot Script Unload Function
#---------------------------------------
def Unload():
	global LocalSocket
	global TwitchPubSubAPI
	global Logger
	if LocalSocket:
		LocalSocket.Close(1000, "Program exit")
		LocalSocket = None
		Logger.debug("LocalSocket Disconnected")
	if TwitchPubSubAPI:
		TwitchPubSubAPI.Close(1000, "Program exit")
		TwitchPubSubAPI = None
		Logger.debug("TwitchPubSubAPI Disconnected")
	if Logger:
		for handler in Logger.handlers[:]:
			Logger.removeHandler(handler)
		Logger = None

#---------------------------------------
#   Chatbot Save Settings Function
#---------------------------------------
def ReloadSettings(jsondata):
	global Logger
	global ScriptSettings
	ScriptSettings.Reload(jsondata)
	if Logger:
		Logger.debug({ "event": "{0}_UPDATE_SETTINGS".format(ScriptName.upper()), "data": ScriptSettings.__dict__ })
		SendEvent({ "event": "{0}_UPDATE_SETTINGS".format(ScriptName.upper()), "data": ScriptSettings.__dict__ })
		ScriptToggled(False)
		ScriptToggled(True)

#---------------------------------------
#   Chatbot Toggle Function
#---------------------------------------
def ScriptToggled(state):
	global Logger
	if state:
		if not Logger:
			Init()
		global ScriptSettings
		LocalSocket.Connect()
		Parent.AddCooldown(ScriptName, "LocalSocket", 10)
		if ScriptSettings.JTVToken and ScriptSettings.JTVClientID and ScriptSettings.StreamerName:
			TwitchPubSubAPI.Connect()
			Parent.AddCooldown(ScriptName, "TwitchPubSubPong", 10)
			Parent.AddCooldown(ScriptName, "TwitchPubSubPing", 270)
		else:
			Logger.warning("Streamer name, Twitch Client ID and/or Twitch Oauth Token not configured")
		Logger.debug("Script toggled on")
	else:
		if Logger:
			Logger.debug("Script toggled off")
			Unload()

#---------------------------------------
#   Chatbot Execute Function
#---------------------------------------
def Execute(data):
	pass

#---------------------------------------
#   Chatbot Tick Function
#---------------------------------------
def Tick():
	global Logger
	if not Logger:
		return
	global LocalSocket
	global LocalSocketIsConnected
	if not Parent.IsOnCooldown(ScriptName, "LocalSocket") and LocalSocket and not LocalSocketIsConnected and ScriptSettings.LocalWebsocket:
		Logger.warning("No EVENT_CONNECTED received from LocalSocket, reconnecting")
		try:
			LocalSocket.Close(1006, "No connection confirmation received")
		except:
			Logger.error("Could not close LocalSocket gracefully")
		LocalSocket.Connect()
		Parent.AddCooldown(ScriptName, "LocalSocket", 10)
	if not Parent.IsOnCooldown(ScriptName, "LocalSocket") and LocalSocket and not LocalSocket.IsAlive:
		Logger.warning("LocalSocket seems dead, reconnecting")
		try:
			LocalSocket.Close(1006, "No connection")
		except:
			Logger.error("Could not close LocalSocket gracefully")
		LocalSocket.Connect()
		Parent.AddCooldown(ScriptName, "LocalSocket", 10)
	global TwitchPubSubAPIPong
	if not Parent.IsOnCooldown(ScriptName, "TwitchPubSubPong") and not TwitchPubSubAPIPong and ScriptSettings.JTVToken:
		Logger.warning("No PONG received from TwitchPubSub, reconnecting")
		try:
			TwitchPubSubAPI.Close()
		except:
			Logger.error("Could not close TwitchPubSub socket gracefully")
		TwitchPubSubAPI.Connect()
		Parent.AddCooldown(ScriptName, "TwitchPubSubPong", 10)
	if not Parent.IsOnCooldown(ScriptName, "TwitchPubSubPing"):
		if TwitchPubSubAPI.IsAlive:
			TwitchPubSubAPI.Send(json.dumps({ "type": "PING" }))
			TwitchPubSubAPIPong = False
			Parent.AddCooldown(ScriptName, "TwitchPubSubPong", 10)
			Logger.debug(json.dumps({ "type": "PING" }))
		else:
			Logger.warning("TwitchPubSubAPI seems dead, reconnecting")
			try:
				TwitchPubSubAPI.Close()
			except:
				Logger.error("Could not close TwitchPubSub socket gracefully")
			TwitchPubSubAPI.Connect()
		Parent.AddCooldown(ScriptName, "TwitchPubSubPing", 270)

#---------------------------------------
#   LocalSocket Connect Function
#---------------------------------------
def LocalSocketConnected(ws, data):
	global Logger
	global ScriptSettings
	Auth = {
		"author": Creator,
		"website": Website,
		"api_key": ScriptSettings.LocalWebsocketAPIKey,
		"events": []
	}
	ws.Send(json.dumps(Auth))
	Logger.debug("Auth: {0}".format(json.dumps(Auth)))

#---------------------------------------
#   LocalSocket Disconnect Function
#---------------------------------------
def LocalSocketDisconnected(ws, data):
	global Logger
	global LocalSocketIsConnected
	LocalSocketIsConnected = False
	if data.Reason:
		Logger.debug("{0}: {1}".format(data.Code, data.Reason))
	elif data.Code == 1000 or data.Code == 1005:
		Logger.debug("{0}: Normal exit".format(data.Code))
	else:
		Logger.debug("{0}: Unknown reason".format(data.Code))
	if not data.WasClean:
		Logger.warning("Unclean socket disconnect")

#---------------------------------------
#   LocalSocket Error Function
#---------------------------------------
def LocalSocketError(ws, data):
	global Logger
	Logger.error(data.Message)
	if data.Exception:
		Logger.debug(data.Exception, exc_info=True)

#---------------------------------------
#   LocalSocket Event Function
#---------------------------------------
def LocalSocketEvent(ws, data):
	global Logger
	if data.IsText:
		event = json.loads(data.Data)
		if "data" in event and isinstance(event["data"], str):
			event["data"] = json.loads(event["data"])
		if event["event"] == "EVENT_CONNECTED":
			global LocalSocketIsConnected
			LocalSocketIsConnected = True
			Logger.info(event["data"]["message"])
		else:
			Logger.debug("Unhandled event: {0}: {1}".format(event["event"], json.dumps(event["data"])))

#---------------------------------------
#   TwitchPubSubAPI Connect Function
#---------------------------------------
def TwitchPubSubAPIConnected(ws, data):
	global Logger
	global ScriptSettings
	try:
		ID = GetTwitchUserID(ScriptSettings.StreamerName)
		if not ID:
			Logger.critical("Could not obtain Twitch user ID")
			return
		Topics = list()
		if ScriptSettings.TwitchBits or ScriptSettings.MirrorAll:
			Topics.append("channel-bits-events-v2.{0}".format(ID))
		if ScriptSettings.TwitchSub or ScriptSettings.MirrorAll:
			Topics.append("channel-subscribe-events-v1.{0}".format(ID))
		if ScriptSettings.TwitchChannelPoints or ScriptSettings.MirrorAll:
			Topics.append("channel-points-channel-v1.{0}".format(ID))
		Auth = {
			"type": "LISTEN",
			"nonce": Nonce(),
			"data": {
				"topics": Topics,
				"auth_token": ScriptSettings.JTVToken
			}
		}
		Logger.debug("Auth: {0}".format(json.dumps(Auth)))
		ws.Send(json.dumps(Auth))
		Logger.debug("Connected")
	except Exception as e:
		Logger.debug(e, exc_info=True)

#---------------------------------------
#   TwitchPubSubAPI Disconnect Function
#---------------------------------------
def TwitchPubSubAPIDisconnected(ws, data):
	global Logger
	if data.Reason:
		Logger.debug("{0}: {1}".format(data.Code, data.Reason))
	elif data.Code == 1000 or data.Code == 1005:
		Logger.debug("{0}: Normal exit".format(data.Code))
	else:
		Logger.debug("{0}: Unknown reason".format(data.Code))
	if not data.WasClean:
		Logger.warning("Unclean socket disconnect")

#---------------------------------------
#   TwitchPubSubAPI Error Function
#---------------------------------------
def TwitchPubSubAPIError(ws, data):
	global Logger
	Logger.error(data.Message)
	if data.Exception:
		Logger.debug(data.Exception, exc_info=True)

#---------------------------------------
#   TwitchPubSubAPI Event Function
#---------------------------------------
def TwitchPubSubAPIEvent(ws, data):
	global Logger
	event = json.loads(data.Data, encoding="utf-8")
	global ScriptSettings
	if event["type"] == "RESPONSE":
		if event["error"]:
			Logger.error("LISTEN request with nonce {0} returned {1}".format(event["nonce"], event["error"]))
		else:
			Logger.debug("LISTEN request with nonce {0} accepted".format(event["nonce"]))
			Logger.info("Twitch PubSub socket connected")
	elif event["type"] == "RECONNECT":
		Logger.warning("RECONNECT requested")
		ws.Close(1000, "Reconnect requested")
		ws.Connect()
	elif event["type"] == "PONG":
		Logger.debug("{0}".format(json.dumps(event)))
		global TwitchPubSubAPIPong
		TwitchPubSubAPIPong = True
	elif event["type"] == "MESSAGE":
		topic = re.match(r"(?P<topic>[\w-]+)\.[\d]+", event["data"]["topic"])
		if isinstance(event["data"]["message"], str):
			event["data"]["message"] = json.loads(event["data"]["message"])
		Logger.debug("Event received: {0}".format(json.dumps(event, indent=4)))
		if ScriptSettings.MirrorAll:
			global LocalSocket
			LocalSocket.Send(json.dumps({ "event": "TWITCHPUBSUB", "data": event["data"] }))
		if topic.group("topic") == "channel-bits-events-v2" and ScriptSettings.TwitchBits:
			is_new_badge_tier = False
			new_badge = None
			message = event["data"]["message"]["data"]
			if not "display_name" in message and "user_name" in message and "is_anonymous" in message and not message["is_anonymous"]:
				message["display_name"] = Parent.GetDisplayName(message["user_name"])
			if "badge_entitlement" in message and message["badge_entitlement"] and "new_version" in message["badge_entitlement"] and "previous_version" in message["badge_entitlement"] and message["badge_entitlement"]["new_version"] > 0:
				is_new_badge_tier = True
				new_badge = message["badge_entitlement"]["new_version"]
			SendEvent(TwitchBits(message.get("user_id"), message.get("user_name"), message.get("display_name"), message.get("bits_used", 0), message.get("total_bits_used", 0), message.get("chat_message"), message.get("is_anonymous", False), is_new_badge_tier=is_new_badge_tier, badge_tier=new_badge))
		elif topic.group("topic") == "channel-subscribe-events-v1" and ScriptSettings.TwitchSub:
			message = event["data"]["message"]
			if "sub_message" in message and "message" in message["sub_message"]:
				message["message"] = message["sub_message"]["message"]
			if "context" in message:
				message["sub_type"] = message["context"]
			args = ArgsToDict(TwitchSubscriptions.func_code.co_varnames[:TwitchSubscriptions.func_code.co_argcount], message)
			SendEvent(TwitchSubscriptions(**args))
		elif topic.group("topic") == "channel-points-channel-v1" and ScriptSettings.TwitchChannelPoints:
			message = event["data"]["message"]["data"]["redemption"]
			SendEvent(TwitchChannelPoints(message["user"]["id"], message["user"]["login"], message["user"]["display_name"], message["reward"]["id"], message["reward"]["cost"], message["reward"]["title"], prompt=message["reward"]["prompt"], is_test=False, is_repeat=None))
