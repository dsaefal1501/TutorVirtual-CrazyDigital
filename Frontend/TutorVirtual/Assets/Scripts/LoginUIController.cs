using UnityEngine;
using UnityEngine.UIElements;

[ExecuteAlways]
public class LoginUIController : MonoBehaviour
{
	[Header("Gradient Settings")]
	[SerializeField] private Color gradientTopColor = new Color32(217, 227, 241, 255);
	[SerializeField] private Color gradientBottomColor = new Color32(202, 224, 255, 255);

	[Header("Shadow Settings")]
	[SerializeField] private Color shadowColor = new Color(0.2f, 0.35f, 0.55f, 0.5f);
	[SerializeField] private int shadowRadius = 20; 
	[SerializeField] private float shadowScale = 1.15f; 
	[SerializeField] private Vector2 shadowOffset = new Vector2(0, 5);

	private UIDocument _uiDocument;

	private void OnEnable()
	{
		_uiDocument = GetComponent<UIDocument>();
		if (_uiDocument == null) return;
        
		_uiDocument.rootVisualElement.schedule.Execute(UpdateUI);
	}

	private void OnValidate()
	{
		if (_uiDocument == null) _uiDocument = GetComponent<UIDocument>();
		if (_uiDocument != null && _uiDocument.rootVisualElement != null)
		{
			_uiDocument.rootVisualElement.schedule.Execute(UpdateUI);
		}
	}

	private void UpdateUI()
	{
		var root = _uiDocument.rootVisualElement;
		if (root == null) return;

		var backgroundElement = root.Q<VisualElement>("Background");
		if (backgroundElement != null) ApplyGradientBackground(backgroundElement);

		SetupButtonShadow(root.Q<Button>("BtnAlumno"));
		SetupButtonShadow(root.Q<Button>("BtnInstructor"));
	}

	private void SetupButtonShadow(Button btn)
	{
		if (btn == null) return;

		// Si el botón no tiene tamaño aun, esperamos
		if (float.IsNaN(btn.resolvedStyle.width) || btn.resolvedStyle.width < 1)
		{
			btn.schedule.Execute(() => SetupButtonShadow(btn));
			return;
		}

		// Comprobamos si ya tiene el wrapper
		if (btn.parent != null && btn.parent.name == "shadow-wrapper")
		{
			UpdateExistingShadow(btn.parent);
		}
		else
		{
			CreateShadowWrapper(btn);
		}
	}

	private void UpdateExistingShadow(VisualElement wrapper)
	{
		// Buscamos nuestro componente Shadow personalizado
		var shadow = wrapper.Q<Shadow>(); 
		if (shadow != null)
		{
			// La propiedad 'color' de VisualElement es la que usa el script Shadow para el tinte central
			shadow.style.color = shadowColor; 
			shadow.shadowCornerRadius = shadowRadius;
			shadow.shadowScale = shadowScale;
			shadow.shadowOffsetX = (int)shadowOffset.x;
			shadow.shadowOffsetY = (int)shadowOffset.y;
            
			// Forzamos el repintado
			shadow.MarkDirtyRepaint();
		}
        
		// Sincronizamos el radio del botón con el de la sombra para que quede bonito
		var btn = wrapper.Q<Button>();
		if (btn != null)
		{
			// El botón debe tener el mismo radio o un poco menos
			btn.style.borderTopLeftRadius = shadowRadius;
			btn.style.borderTopRightRadius = shadowRadius;
			btn.style.borderBottomLeftRadius = shadowRadius;
			btn.style.borderBottomRightRadius = shadowRadius;
		}
	}

	private void CreateShadowWrapper(Button btn)
	{
		// 1. Crear Wrapper
		VisualElement wrapper = new VisualElement();
		wrapper.name = "shadow-wrapper";
		wrapper.style.width = btn.resolvedStyle.width;
		wrapper.style.height = btn.resolvedStyle.height;
		// Copiar márgenes para mantener posición
		wrapper.style.marginTop = btn.resolvedStyle.marginTop;
		wrapper.style.marginBottom = btn.resolvedStyle.marginBottom;
		wrapper.style.marginLeft = btn.resolvedStyle.marginLeft;
		wrapper.style.marginRight = btn.resolvedStyle.marginRight;
        
		// 2. Crear nuestra Sombra Mesh (Instanciamos la clase Shadow)
		Shadow shadow = new Shadow();
		shadow.name = "mesh-shadow";
		shadow.style.position = Position.Absolute;
		shadow.style.width = Length.Percent(100);
		shadow.style.height = Length.Percent(100);
        
		// Configuramos valores iniciales
		shadow.style.color = shadowColor;
		shadow.shadowCornerRadius = shadowRadius;
		shadow.shadowScale = shadowScale;
		shadow.shadowOffsetX = (int)shadowOffset.x;
		shadow.shadowOffsetY = (int)shadowOffset.y;

		// 3. Configurar Botón
		btn.style.marginTop = 0;
		btn.style.marginBottom = 0;
		btn.style.marginLeft = 0;
		btn.style.marginRight = 0;
		btn.style.width = Length.Percent(100);
		btn.style.height = Length.Percent(100);
		btn.style.borderTopLeftRadius = shadowRadius;
		btn.style.borderTopRightRadius = shadowRadius;
		btn.style.borderBottomLeftRadius = shadowRadius;
		btn.style.borderBottomRightRadius = shadowRadius;

		// 4. Intercambiar en jerarquía
		VisualElement originalParent = btn.parent;
		int originalIndex = originalParent.IndexOf(btn);
		originalParent.Remove(btn);
        
		originalParent.Insert(originalIndex, wrapper);
		wrapper.Add(shadow); // La sombra va detrás
		wrapper.Add(btn);    // El botón va delante
	}

	private void ApplyGradientBackground(VisualElement element)
	{
		Texture2D gradientTexture = new Texture2D(1, 2);
		gradientTexture.SetPixel(0, 0, gradientBottomColor);
		gradientTexture.SetPixel(0, 1, gradientTopColor);
		gradientTexture.filterMode = FilterMode.Bilinear;
		gradientTexture.wrapMode = TextureWrapMode.Clamp;
		gradientTexture.Apply();
		element.style.backgroundImage = new StyleBackground(gradientTexture);
	}
}