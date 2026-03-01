class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/e5/bb/430ac2bc7c58df082cc4b0c0267a8a9bef6328dfac633702eadd93ee6d01/agentops_mcp_server-0.1.1.tar.gz"
  sha256 "f6438eee32ba4bc6b372748ed293f73d3563add262bc282d9c9628319938c282"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
