using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using TMPro;
using UnityEngine.UI; // Necesario si quieres manipular componentes Button

[System.Serializable]
public class Pregunta
{
	public string pregunta;
	public string[] opciones;
	public int correcta;
}

[System.Serializable]
public class ExamenData
{
	public List<Pregunta> preguntas;
}

public class FastApiConnector : MonoBehaviour
{
	private string urlExamen = "http://192.168.18.6:8000/examen";

	public TextMeshProUGUI pregunta, resp1, resp2, resp3, resp4;
	// El índice de la respuesta correcta de la pregunta actual
	public int indiceCorrecto; 

	[ContextMenu("Descargar Examen")]
	public void DescargarExamen()
	{
		StartCoroutine(GetExamenRequest(urlExamen));
	}

	IEnumerator GetExamenRequest(string uri)
	{
		using (UnityWebRequest webRequest = UnityWebRequest.Get(uri))
		{
			yield return webRequest.SendWebRequest();

			if (webRequest.result == UnityWebRequest.Result.Success)
			{
				string json = webRequest.downloadHandler.text;
				ExamenData data = JsonUtility.FromJson<ExamenData>(json);

				if (data.preguntas != null && data.preguntas.Count > 0)
				{
					Pregunta p = data.preguntas[0];
                
					pregunta.text = p.pregunta;
					resp1.text = p.opciones[0];
					resp2.text = p.opciones[1];
					resp3.text = p.opciones[2];
					resp4.text = p.opciones[3];
                    
					// CORRECCIÓN: Accedemos a la variable 'correcta' del objeto
					indiceCorrecto = p.correcta;
				}
			}
			else
			{
				Debug.LogError("Error al conectar con la API: " + webRequest.error);
			}
		}
	}

	// Función para asignar a tus botones en el Inspector de Unity
	public void ValidarRespuesta(int indiceBoton)
	{
		if (indiceBoton == indiceCorrecto)
		{
			Debug.Log("<color=green>¡Correcto!</color>");
			// Aquí puedes llamar a DescargarExamen() para pasar a la siguiente
			DescargarExamen();
		}
		else
		{
			Debug.Log("<color=red>Fallaste. Inténtalo de nuevo.</color>");
		}
	}
}