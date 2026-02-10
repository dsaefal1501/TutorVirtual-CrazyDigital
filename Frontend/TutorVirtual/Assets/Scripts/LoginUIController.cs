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
	[SerializeField] private Vector2 shadowOffset = new Vector2(0, 5);
	[SerializeField] private float buttonCornerRadius = 30f;

	private UIDocument _uiDocument;

	private void OnEnable()
	{
		_uiDocument = GetComponent<UIDocument>();
		if (_uiDocument == null) return;
        
		UpdateUI();
	}

	private void OnValidate()
	{
		if (_uiDocument == null) _uiDocument = GetComponent<UIDocument>();
		if (_uiDocument != null && _uiDocument.rootVisualElement != null)
		{
			UpdateUI();
		}
	}

	private void UpdateUI()
	{
		var root = _uiDocument.rootVisualElement;
		if (root == null) return;

		var backgroundElement = root.Q<VisualElement>("Background");
		if (backgroundElement != null)
		{
			ApplyGradientBackground(backgroundElement);
		}

		UpdateOrSetupShadow(root.Q<Button>("BtnAlumno"));
		UpdateOrSetupShadow(root.Q<Button>("BtnInstructor"));
	}

	private void UpdateOrSetupShadow(Button btn)
	{
		if (btn == null) return;

		if (btn.parent != null && btn.parent.name == "shadow-wrapper")
		{
			UpdateExistingShadow(btn.parent);
		}
		else
		{
			if (float.IsNaN(btn.resolvedStyle.width))
			{
				btn.schedule.Execute(() => UpdateOrSetupShadow(btn));
				return;
			}
			CreateShadowWrapper(btn);
		}
	}

	private void UpdateExistingShadow(VisualElement wrapper)
	{
		var shadow = wrapper.Q<VisualElement>("shadow");
		if (shadow != null)
		{
			shadow.style.backgroundColor = shadowColor;
			shadow.style.top = shadowOffset.y;
			shadow.style.left = shadowOffset.x;
			shadow.style.borderTopLeftRadius = buttonCornerRadius;
			shadow.style.borderTopRightRadius = buttonCornerRadius;
			shadow.style.borderBottomLeftRadius = buttonCornerRadius;
			shadow.style.borderBottomRightRadius = buttonCornerRadius;
		}

		var btn = wrapper.Q<Button>();
		if (btn != null)
		{
			btn.style.borderTopLeftRadius = buttonCornerRadius;
			btn.style.borderTopRightRadius = buttonCornerRadius;
			btn.style.borderBottomLeftRadius = buttonCornerRadius;
			btn.style.borderBottomRightRadius = buttonCornerRadius;
		}
	}

	private void CreateShadowWrapper(Button btn)
	{
		VisualElement wrapper = new VisualElement();
		wrapper.name = "shadow-wrapper";
		wrapper.style.width = btn.resolvedStyle.width;
		wrapper.style.height = btn.resolvedStyle.height;
		wrapper.style.marginTop = btn.resolvedStyle.marginTop;
		wrapper.style.marginBottom = btn.resolvedStyle.marginBottom;
		wrapper.style.marginLeft = btn.resolvedStyle.marginLeft;
		wrapper.style.marginRight = btn.resolvedStyle.marginRight;
        
		VisualElement shadow = new VisualElement();
		shadow.name = "shadow";
		shadow.style.position = Position.Absolute;
		shadow.style.width = Length.Percent(100);
		shadow.style.height = Length.Percent(100);
		shadow.style.backgroundColor = shadowColor;
		shadow.style.top = shadowOffset.y;
		shadow.style.left = shadowOffset.x;
		shadow.style.borderTopLeftRadius = buttonCornerRadius;
		shadow.style.borderTopRightRadius = buttonCornerRadius;
		shadow.style.borderBottomLeftRadius = buttonCornerRadius;
		shadow.style.borderBottomRightRadius = buttonCornerRadius;

		btn.style.marginTop = 0;
		btn.style.marginBottom = 0;
		btn.style.marginLeft = 0;
		btn.style.marginRight = 0;
		btn.style.width = Length.Percent(100);
		btn.style.height = Length.Percent(100);
		btn.style.borderTopLeftRadius = buttonCornerRadius;
		btn.style.borderTopRightRadius = buttonCornerRadius;
		btn.style.borderBottomLeftRadius = buttonCornerRadius;
		btn.style.borderBottomRightRadius = buttonCornerRadius;

		VisualElement originalParent = btn.parent;
		int originalIndex = originalParent.IndexOf(btn);

		originalParent.Remove(btn);
		originalParent.Insert(originalIndex, wrapper);
        
		wrapper.Add(shadow);
		wrapper.Add(btn);
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