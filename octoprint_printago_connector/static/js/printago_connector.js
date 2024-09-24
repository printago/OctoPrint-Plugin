$(function() {
    function PrintagoViewModel(parameters) {
        var self = this;

        self.global_settings = parameters[0];

        self.showUserCredentials = ko.observable(false);
        self.showClientID = ko.observable(false);

        self.settings = undefined;
        self.availableProtocols = ko.observableArray(['MQTTv31','MQTTv311']);

        self.onBeforeBinding = function () {
            self.settings = self.global_settings.settings.plugins.printago_connector;

            // show credential options if username is set
            self.showUserCredentials(!!self.settings.broker.username());

            // show client_id options if client_id is set
            self.showClientID(!!self.settings.client.client_id());
        };
    }

    ADDITIONAL_VIEWMODELS.push([
        PrintagoViewModel,
        ["settingsViewModel"],
        ["#settings_plugin_printago"]
    ]);
});
