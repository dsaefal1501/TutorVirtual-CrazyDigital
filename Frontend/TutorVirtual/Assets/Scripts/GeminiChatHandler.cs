using UnityEngine;
using UnityEditor.UI;
using UnityEngine.UI;
using UnityEngine.Networking;
using TMPro;
using System.Collections;
using System.Text;

[System.Serializable]
public class PostData 
{
	public string texto;
	public int usuario_id = 1; // Añadimos esto para que FastAPI esté contento
}

public class GeminiChatHandler : MonoBehaviour
{
	public TMP_InputField inputField;
	public TMP_InputField inputFieldPruebaExpresiones;
	public TextMeshProUGUI textoRespuesta;
	
	public Image expressionImage;
	public Sprite Happy, Thinking, Angry, Neutral, Explaining;
	
    
	[Header("Configuración")]
	[SerializeField] private string ipServidor; // Pon aquí tu IP real si usas móvil
	private string urlApi;

	void Start()
	{
		urlApi = $"http://{ipServidor}:8000/ask/stream";
		inputField.onSubmit.AddListener(delegate { EnviarAFastApi(); });
	}
	
	// Update is called every frame, if the MonoBehaviour is enabled.
	protected void Update()
	{
		if (inputFieldPruebaExpresiones.text.Contains("feliz"))
			expressionImage.sprite = Happy;
		else if (inputFieldPruebaExpresiones.text.Contains("pensando"))
			expressionImage.sprite = Thinking;
		else if (inputFieldPruebaExpresiones.text.Contains("enfadado"))
			expressionImage.sprite = Angry;
		else if (inputFieldPruebaExpresiones.text.Contains("neutral"))
			expressionImage.sprite = Neutral;
		else if (inputFieldPruebaExpresiones.text.Contains("explicando"))
			expressionImage.sprite = Explaining;
	}

	public void EnviarAFastApi()
	{
		if (!string.IsNullOrEmpty(inputField.text))
		{
			StartCoroutine(PostRequestStream(inputField.text));
			inputField.text = "";
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