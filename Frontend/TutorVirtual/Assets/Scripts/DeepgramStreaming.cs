using System;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using Newtonsoft.Json.Linq;

public class DeepgramConnector : MonoBehaviour
{
	[Header("Referencias")]
	[SerializeField] private GeminiChatHandler chatHandler;

	[Header("Deepgram Config")]
	[SerializeField] private string apiKey = "169777c4fd4d79c294d2a083849a47f625b24580";
	[Range(0.01f, 0.5f)]
	[SerializeField] private float sendInterval = 0.01f;
	[SerializeField] private int sampleRate = 44100;

	private ClientWebSocket _webSocket;
	private AudioClip _microphoneClip;
	private string _microphoneDevice;
	private bool _isRecording;
	private int _lastSamplePosition;
	private float _timer;
	private CancellationTokenSource _cancellationTokenSource;
	private List<float> _audioBuffer;

	// Variables para sincronización con Main Thread
	private string _latestTranscript = "";
	private bool _hasNewTranscript = false;
	private bool _shouldSendToGemini = false;
	private object _lock = new object();

	private async void Start()
	{
		if (Microphone.devices.Length == 0) return;

		_audioBuffer = new List<float>();
		_microphoneDevice = Microphone.devices[0];
		_microphoneClip = Microphone.Start(_microphoneDevice, true, 10, sampleRate);
		_isRecording = true;
		_lastSamplePosition = 0;

		await ConnectToDeepgram();
	}

	private void Update()
	{
		// 1. Manejo de Audio y Envío (Chunking)
		if (_isRecording && _webSocket != null && _webSocket.State == WebSocketState.Open)
		{
			ProcessAudioInput();
		}

		// 2. Actualización de UI (Main Thread)
		lock (_lock)
		{
			if (_hasNewTranscript)
			{
				if (chatHandler != null && chatHandler.inputField != null)
				{
					chatHandler.inputField.text = _latestTranscript;
				}
				_hasNewTranscript = false;
			}

			if (_shouldSendToGemini)
			{
				if (chatHandler != null)
				{
					chatHandler.EnviarAFastApi();
				}
				_shouldSendToGemini = false;
				_latestTranscript = ""; 
			}
		}
	}

	private void ProcessAudioInput()
	{
		int currentPosition = Microphone.GetPosition(_microphoneDevice);
        
		if (currentPosition < _lastSamplePosition)
		{
			int samplesToEnd = _microphoneClip.samples - _lastSamplePosition;
			if (samplesToEnd > 0)
			{
				float[] endSamples = new float[samplesToEnd];
				_microphoneClip.GetData(endSamples, _lastSamplePosition);
				_audioBuffer.AddRange(endSamples);
			}
			_lastSamplePosition = 0;
		}

		int samplesToRead = currentPosition - _lastSamplePosition;
		if (samplesToRead > 0)
		{
			float[] newSamples = new float[samplesToRead];
			_microphoneClip.GetData(newSamples, _lastSamplePosition);
			_audioBuffer.AddRange(newSamples);
			_lastSamplePosition = currentPosition;
		}

		_timer += Time.deltaTime;
		if (_timer >= sendInterval && _audioBuffer.Count > 0)
		{
			float[] samplesToSend = _audioBuffer.ToArray();
			_audioBuffer.Clear();
			_timer = 0;

			byte[] pcmData = ConvertToPCM16(samplesToSend);
			_ = SendAudioData(pcmData);
		}
	}

	private async Task ConnectToDeepgram()
	{
		_webSocket = new ClientWebSocket();
		_webSocket.Options.SetRequestHeader("Authorization", "Token " + apiKey);

		string url = $"wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate={sampleRate}&channels=1&language=es&interim_results=true&endpointing=100&smart_format=true";
        
		_cancellationTokenSource = new CancellationTokenSource();

		try
		{
			await _webSocket.ConnectAsync(new Uri(url), CancellationToken.None);
			_ = ReceiveTranscript(_cancellationTokenSource.Token);
		}
			catch (Exception ex)
			{
				Debug.LogError(ex.Message);
			}
	}

	private async Task SendAudioData(byte[] audioData)
	{
		if (_webSocket.State == WebSocketState.Open)
		{
			try
			{
				await _webSocket.SendAsync(new ArraySegment<byte>(audioData), WebSocketMessageType.Binary, true, CancellationToken.None);
			}
				catch { }
		}
	}

	private async Task ReceiveTranscript(CancellationToken token)
	{
		var buffer = new byte[1024 * 16];

		while (_webSocket.State == WebSocketState.Open && !token.IsCancellationRequested)
		{
			try
			{
				var result = await _webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), token);

				if (result.MessageType == WebSocketMessageType.Text)
				{
					string json = Encoding.UTF8.GetString(buffer, 0, result.Count);
					ProcessDeepgramResponse(json);
				}
				else if (result.MessageType == WebSocketMessageType.Close)
				{
					await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, string.Empty, CancellationToken.None);
				}
			}
				catch { }
		}
	}

	private void ProcessDeepgramResponse(string json)
	{
		try
		{
			JObject response = JObject.Parse(json);
            
			var alternatives = response["channel"]?["alternatives"];
			if (alternatives == null || !alternatives.HasValues) return;

			var transcript = alternatives[0]["transcript"]?.ToString();
			var isFinal = response["is_final"]?.ToObject<bool>() ?? false;

			if (!string.IsNullOrEmpty(transcript))
			{
				lock (_lock)
				{
					_latestTranscript = transcript;
					_hasNewTranscript = true;

					if (isFinal)
					{
						_shouldSendToGemini = true;
					}
				}
			}
		}
			catch { }
	}

	private byte[] ConvertToPCM16(float[] samples)
	{
		short[] intData = new short[samples.Length];
		byte[] bytesData = new byte[samples.Length * 2];

		for (int i = 0; i < samples.Length; i++)
		{
			float sample = Mathf.Clamp(samples[i], -1f, 1f);
			intData[i] = (short)(sample * 32767);
			byte[] byteArr = BitConverter.GetBytes(intData[i]);
			byteArr.CopyTo(bytesData, i * 2);
		}

		return bytesData;
	}

	private async void OnDestroy()
	{
		_isRecording = false;
		if (!string.IsNullOrEmpty(_microphoneDevice)) Microphone.End(_microphoneDevice);
		if (_cancellationTokenSource != null) _cancellationTokenSource.Cancel();

		if (_webSocket != null && _webSocket.State == WebSocketState.Open)
		{
			await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Cierre", CancellationToken.None);
			_webSocket.Dispose();
		}
	}
}