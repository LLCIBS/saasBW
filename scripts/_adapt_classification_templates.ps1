$files = @(
  'web_interface/templates/classification/rules.html',
  'web_interface/templates/classification/schedules.html',
  'web_interface/templates/classification/learning_analytics.html',
  'web_interface/templates/classification/review.html',
  'web_interface/templates/classification/call_detail.html',
  'web_interface/templates/classification/training.html',
  'web_interface/templates/classification/add_example.html',
  'web_interface/templates/classification/correct_classifications.html'
)

$prefix = @"
{% block content %}
{% include 'partials/sidebar.html' %}
<main class="col-md-9 col-lg-10 main-content">
    <div class="p-4">
        {% include 'classification/_nav.html' %}
"@

$suffixBeforeJs = @"
    </div>
</main>
{% endblock %}

{% block extra_js %}
"@

foreach ($file in $files) {
  $content = Get-Content -Raw -Path $file

  $content = $content.Replace('{% block scripts %}', '{% block extra_js %}')

  $content = $content.Replace("url_for('review_calls'", "url_for('classification.review_page'")
  $content = $content.Replace("url_for('call_detail'", "url_for('classification.call_detail_page'")
  $content = $content.Replace("url_for('upload_file')", "url_for('classification.classify_page')")
  $content = $content.Replace("url_for('training_examples'", "url_for('classification.training_page'")
  $content = $content.Replace("url_for('add_example'", "url_for('classification.training_add_page'")
  $content = $content.Replace("url_for('toggle_example'", "url_for('classification.training_toggle_example'")
  $content = $content.Replace("url_for('delete_example'", "url_for('classification.training_delete_example'")
  $content = $content.Replace("url_for('learning_analytics'", "url_for('classification.learning_analytics_page'")

  $content = $content.Replace('/api/system_prompts', '/api/system-prompts')
  $content = $content.Replace('/api/classification_rules', '/api/classification-rules')
  $content = $content.Replace('/api/critical_rules', '/api/critical-rules')
  $content = $content.Replace('/api/generate_prompt_preview', '/api/generate-prompt-preview')
  $content = $content.Replace('/api/reclassify_call', '/api/reclassify-call')
  $content = $content.Replace('/api/save_reclassification', '/api/save-reclassification')
  $content = $content.Replace('/api/mark_as_correct', '/api/mark-as-correct')
  $content = $content.Replace('/api/success_stats', '/api/success-stats')
  $content = $content.Replace('/api/correct_classifications', '/api/correct-classifications')
  $content = $content.Replace('/api/export_learning_report', '/api/export-learning-report')

  $content = $content.Replace('/correct_call', '/classification/api/save-reclassification')
  $content = $content.Replace("document.querySelector('main .content-wrapper')", "document.querySelector('.main-content .p-4') || document.body")
  $content = $content.Replace("document.querySelector('.content-wrapper')", "document.querySelector('.main-content .p-4') || document.body")

  $content = $content.Replace('/api/', '/classification/api/')

  if (-not $content.Contains("{% include 'partials/sidebar.html' %}")) {
    $content = $content.Replace('{% block content %}', $prefix)
    $content = $content.Replace("{% endblock %}`r`n`r`n{% block extra_js %}", $suffixBeforeJs)
    $content = $content.Replace("{% endblock %}`n`n{% block extra_js %}", $suffixBeforeJs)
  }

  Set-Content -Path $file -Value $content -Encoding UTF8
}
