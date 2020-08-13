#---------------------------------------
#   Import Libraries
#---------------------------------------
import logging
from logging.handlers import TimedRotatingFileHandler
import clr
import re
import os
import sys
import time
import codecs
import json
import uuid
clr.AddReference("websocket-sharp.dll")
from WebSocketSharp import WebSocket
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
from CommonEventsTemplates import TwitchBits, TwitchSubscriptions, TwitchChannelPoints

#---------------------------------------
#   [Required] Script Information
#---------------------------------------
ScriptName = 'TwitchPubSubMirror'
Website = 'https://github.com/nossebro/TwitchPubSubMirror'
Creator = 'nossebro'
Version = '0.0.2'
Description = 'Mirrors events from Twitch PubSub socket, and sends them to the local SLCB socket'

#---------------------------------------
#   Script Variables
#---------------------------------------
ScriptSettings = None
TwitchPubSubAPI = None
TwitchPubSubAPIPong = True
Logger = None
LastTime = None
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
			self.__dict__ = MergeLists(defaults, settings)
		except:
			self.__dict__ = defaults

	def DefaultSettings(self, settingsfile=None):
		defaults = dict()
		with codecs.open(settingsfile, encoding="utf-8-sig", mode="r") as f:
			ui = json.load(f, encoding="utf-8")
		for key in ui:
			try:
				defaults[key] = ui[key]['value']
			except:
				if key != "output_file":
					Parent.Log(ScriptName, "DefaultSettings(): Could not find key {0} in settings".format(key))
		return defaults

	def Reload(self, jsondata):
		self.__dict__ = MergeLists(self.DefaultSettings(UIConfigFile), json.loads(jsondata, encoding="utf-8"))

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

def MergeLists(x = dict(), y = dict()):
	z = dict()
	for attr in x:
		if attr not in y:
			z[attr] = x[attr]
		else:
			z[attr] = y[attr]
	return z

def Nonce():
	nonce = uuid.uuid1()
	oauth_nonce = nonce.hex
	return oauth_nonce

def GetTwitchUserID(Username = None):
	global ScriptSettings
	global Logger
	ID = None
	if not Username:
		Username = ScriptSettings.StreamerName
	Header = {
		"Client-ID": ScriptSettings.JTVClientID,
		"Authorization": "Bearer {0}".format(ScriptSettings.JTVToken)
	}
	Logger.debug("Header: {0}".format(json.dumps(Header)))
	result = json.loads(Parent.GetRequest("https://api.twitch.tv/helix/users?login={0}".format(Username.lower()), Header))
	if result["status"] == 200:
		response = json.loads(result["response"])
		Logger.debug("Response: {0}".format(json.dumps(response)))
		ID = response["data"][0]["id"]
		Logger.debug("ID: {0}".format(ID))
	elif "error" in result:
		Logger.error("Error Code {0}: {1}".format(result["status"], result["error"]))
	else:
		Logger.warning("Response unknown: {0}".format(result))
	return ID

def SendEvent(events):
	global Logger
	global ScriptSettings
	for event in events:
		Logger.debug("Sending event: {0}".format(event))
		Parent.BroadcastWsEvent(event["event"], json.dumps(event["data"]))

#---------------------------------------
#   Chatbot Initialize Function
#---------------------------------------
def Init():
	global ScriptSettings
	ScriptSettings = Settings(SettingsFile)
	global Logger
	Logger = GetLogger()
	Parent.BroadcastWsEvent('{0}_UPDATE_SETTINGS'.format(ScriptName.upper()), json.dumps(ScriptSettings.__dict__))
	Logger.debug(json.dumps(ScriptSettings.__dict__), True)

	global TwitchPubSubAPI
	TwitchPubSubAPI = WebSocket("wss://pubsub-edge.twitch.tv")
	TwitchPubSubAPI.OnOpen += TwitchPubSubAPIConnected
	TwitchPubSubAPI.OnClose += TwitchPubSubAPIDisconnected
	TwitchPubSubAPI.OnMessage += TwitchPubSubAPIEvent
	TwitchPubSubAPI.OnError += TwitchPubSubAPIError

	if ScriptSettings.JTVToken and ScriptSettings.JTVClientID and ScriptSettings.StreamerName:
		TwitchPubSubAPI.Connect()
	else:
		Logger.warning("Streamer name, Twitch Client ID and/or Twitch Oauth Token not configured")

	global LastTime
	LastTime = time.time()

#---------------------------------------
#   Chatbot Script Unload Function
#---------------------------------------
def Unload():
	global TwitchPubSubAPI
	global Logger
	if TwitchPubSubAPI:
		TwitchPubSubAPI.Close(1000, "Program exit")
		TwitchPubSubAPI = None
		Logger.debug("TwitchPubSubAPI Disconnected")
	if Logger:
		Logger.handlers.Clear()
		Logger = None

#---------------------------------------
#   Chatbot Save Settings Function
#---------------------------------------
def ReloadSettings(jsondata):
	ScriptSettings.Reload(jsondata)
	Logger.debug("Settings reloaded")
	if TwitchPubSubAPI and not TwitchPubSubAPI.IsAlive:
		if ScriptSettings.JTVToken and ScriptSettings.JTVClientID and ScriptSettings.StreamerName:
			TwitchPubSubAPI.Connect()
		else:
			Logger.warning("Streamer name, Twitch Client ID and/or Twitch Oauth Token not configured")
	Parent.BroadcastWsEvent('{0}_UPDATE_SETTINGS'.format(ScriptName.upper()), json.dumps(ScriptSettings.__dict__))
	Logger.debug(json.dumps(ScriptSettings.__dict__), True)

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
	global LastTime
	global TwitchPubSubAPIPong
	Now = time.time()
	SinceLast = Now - LastTime
	if SinceLast >= 10 and not TwitchPubSubAPIPong and ScriptSettings.JTVToken:
		Logger.warning("No PONG received from TwitchPubSub, reconnecting")
		try:
			TwitchPubSubAPI.Close()
		except:
			Logger.error("Could not close TwitchPubSub socket gracefully")
		TwitchPubSubAPI.Connect()
		LastTime = Now
	if SinceLast >= 270:
		if TwitchPubSubAPI.IsAlive:
			TwitchPubSubAPI.Send(json.dumps({ "type": "PING" }))
			TwitchPubSubAPIPong = False
			Logger.debug(json.dumps({ "type": "PING" }))
		else:
			Logger.warning("TwitchPubSubAPI seems dead, reconnecting")
			try:
				TwitchPubSubAPI.Close()
			except:
				Logger.error("Could not close TwitchPubSub socket gracefully")
			TwitchPubSubAPI.Connect()
		LastTime = Now

#---------------------------------------
#   TwitchPubSubAPI Connect Function
#---------------------------------------
def TwitchPubSubAPIConnected(ws, data):
	global ScriptSettings
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

#---------------------------------------
#   TwitchPubSubAPI Disconnect Function
#---------------------------------------
def TwitchPubSubAPIDisconnected(ws, data):
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
	Logger.error(data.Message)
	if data.Exception:
		Logger.exception(data.Exception)

#---------------------------------------
#   TwitchPubSubAPI Event Function
#---------------------------------------
def TwitchPubSubAPIEvent(ws, data):
	event = json.loads(data.Data, encoding="utf-8")
	Logger.debug("Event received: {0}".format(json.dumps(event, indent=4)))
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
		global TwitchPubSubAPIPong
		TwitchPubSubAPIPong = True
	elif event["type"] == "MESSAGE":
		topic = re.match(r"(?P<topic>[\w-]+)\.[\d]+", event["data"]["topic"])
		event["data"]["message"] = json.loads(event["data"]["message"])
		if topic.group("topic") == "channel-bits-events-v2" and ScriptSettings.TwitchBits:
			message = event["data"]["message"]["data"]
			if not "display_name" in message and "user_name" in message and "is_anonymous" in message and not message["is_anonymous"]:
				message["display_name"] = Parent.GetDisplayName(message["user_name"])
			if "badge_entitlement" in message and message["badge_entitlement"] and "new_version" in message["badge_entitlement"] and "previous_version" in message["badge_entitlement"] and message["badge_entitlement"]["new_version"] > 0:
				message["is_new_badge_tier"] = True
				message["old_badge"] = message["badge_entitlement"]["previous_version"]
				message["new_badge"] = message["badge_entitlement"]["new_version"]
			SendEvent(TwitchBits(message, False))
		elif topic.group("topic") == "channel-subscribe-events-v1" and ScriptSettings.TwitchSub:
			message = event["data"]["message"]
			if "sub_message" in message and "message" in message["sub_message"]:
				message["message"] = message["sub_message"]["message"]
			if "context" in message:
				message["sub_type"] = message["context"]
			SendEvent(TwitchSubscriptions(message, False))
		elif topic.group("topic") == "channel-points-channel-v1" and ScriptSettings.TwitchChannelPoints:
			message = event["data"]["message"]["data"]["redemption"]
			message["user_name"] = message["user"]["login"]
			message["display_name"] = message["user"]["display_name"]
			message["user_id"] = message["user"]["id"]
			message["reward_id"] = message["reward"]["id"]
			message["cost"] = message["reward"]["cost"]
			message["title"] = message["reward"]["title"]
			message["prompt"] = message["reward"]["prompt"]
			SendEvent(TwitchChannelPoints(message))
		else:
			Logger.warning("Unknown topic: {0}".format(topic.group("topic")))
	else:
		Logger.warning("Unknown event: {0}".format(json.dumps(event)))
