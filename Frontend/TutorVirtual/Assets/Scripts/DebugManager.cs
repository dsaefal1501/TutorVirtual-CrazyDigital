using UnityEngine;
using TMPro;

public class DebugManager : MonoBehaviour
{
	[SerializeField] private TextMeshProUGUI fpsText;
    
	[Header("Configuración")]
	[Tooltip("Frecuencia de actualización del texto en segundos")]
	[SerializeField] private float frecuenciaActualizacion = 0.5f;

	private float tiempoAcumulado = 0f;
	private int cuadrosContados = 0;
	
	[SerializeField] private GameObject DebugHUD;

	void Awake()
	{
		// 1. Desactivamos VSync para tener control manual
		QualitySettings.vSyncCount = 1;
	}

	void Update()
	{
		if (Input.GetKeyDown(KeyCode.Escape))
		{
			DebugHUD.SetActive(!DebugHUD.activeInHierarchy);
		}
		
		// Lógica del contador de FPS
		tiempoAcumulado += Time.unscaledDeltaTime;
		cuadrosContados++;

		if (tiempoAcumulado >= frecuenciaActualizacion)
		{
			float fps = cuadrosContados / tiempoAcumulado;
            
			if (fpsText != null)
			{
				fpsText.text = $"FPS: {fps:F0}";
			}

			tiempoAcumulado = 0f;
			cuadrosContados = 0;
		}
	}
}