using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Networking;
using TMPro;
using System.Collections;
using System.Text;

[System.Serializable]
public class PostData 
{
	public string texto;
	public int usuario_id = 1; 
}

public class GeminiChatHandler : MonoBehaviour
{
	public TMP_InputField inputField;
	public TextMeshProUGUI textoRespuesta;
    
	public Image expressionImage;
	public Sprite Happy, Thinking, Angry, Neutral, Explaining;
    
	[Header("Configuración")]
	[SerializeField] private string ipServidor = "127.0.0.1";
	private string urlApi;

	void Start()
	{
		urlApi = $"http://{ipServidor}:8000/ask/stream";
		inputField.onSubmit.AddListener(delegate { EnviarAFastApi(); });
	}
    
	protected void Update()
	{
		if (textoRespuesta.text.Contains("Happy"))
			expressionImage.sprite = Happy;
		else if (textoRespuesta.text.Contains("Thinking"))
			expressionImage.sprite = Thinking;
		else if (textoRespuesta.text.Contains("Angry"))
			expressionImage.sprite = Angry;
		else if (textoRespuesta.text.Contains("Neutral"))
			expressionImage.sprite = Neutral;
		else if (textoRespuesta.text.Contains("Explaining"))
			expressionImage.sprite = Explaining;
	}

	public void EnviarAFastApi()
	{
		if (!string.IsNullOrEmpty(inputField.text))
		{
			string mensajeAEnviar = inputField.text;
			inputField.text = ""; 
			StartCoroutine(PostRequestStream(mensajeAEnviar));
		}
	}

	IEnumerator PostRequestStream(string mensaje)
	{
		textoRespuesta.text = "Pensando...";

		PostData data = new PostData { texto = mensaje };
		string json = JsonUtility.ToJson(data);

		using (UnityWebRequest request = new UnityWebRequest(urlApi, "POST"))
		{
			byte[] bodyRaw = Encoding.UTF8.GetBytes(json);
			request.uploadHandler = new UploadHandlerRaw(bodyRaw);
			request.downloadHandler = new GeminiStreamHandler(textoRespuesta);
			request.SetRequestHeader("Content-Type", "application/json");

			yield return request.SendWebRequest();

			if (request.result != UnityWebRequest.Result.Success)
			{
				Debug.LogError($"Error: {request.error}");
				textoRespuesta.text = $"<color=red>Error: {request.downloadHandler.text}</color>";
			}
		}
	}

	private class GeminiStreamHandler : DownloadHandlerScript
	{
		private TextMeshProUGUI _outputArea;
		private bool _isFirstChunk = true;

		public GeminiStreamHandler(TextMeshProUGUI outputArea) : base()
		{
			_outputArea = outputArea;
		}

		protected override bool ReceiveData(byte[] data, int dataLength)
		{
			if (data == null || dataLength < 1) return false;

			if (_isFirstChunk) {
				_outputArea.text = ""; 
				_isFirstChunk = false;
			}

			string text = Encoding.UTF8.GetString(data, 0, dataLength);
			_outputArea.text += text;
			return true;
		}
	}
}